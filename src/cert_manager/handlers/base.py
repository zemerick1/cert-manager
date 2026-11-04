"""Abstract base class for certificate service handlers."""

import datetime
import logging
import socket
import ssl
from abc import ABC, abstractmethod

from cryptography import x509


class CertificateHandler(ABC):
    """Base class for service-specific certificate deployment handlers."""

    def __init__(self, service_config: dict) -> None:
        self.config = service_config
        name = service_config.get("name", "Unknown")
        self.logger = logging.getLogger(f"cert_manager.handler.{name}")

    @abstractmethod
    def deploy(self, cert_path: str, key_path: str) -> dict:
        """Deploys a certificate to the service.

        Args:
            cert_path: Path to the fullchain.pem file.
            key_path: Path to the privkey.pem file.

        Returns:
            Dict with success, message, and stage. stage names the step
            that produced the result: config, pfx, oauth, cluster, or install.
            Per-node detail is under nodes.
        """

    def check_remote_expiry(self) -> dict:
        """Checks the remote service's certificate expiration via SSL handshake.

        Returns:
            Dict with success, expiry, days_remaining, subject, issuer keys.
        """
        host = self.config.get("host")
        if not host:
            return {"success": False, "message": "No host configured"}

        if "://" in host:
            host = host.split("://", 1)[1]

        port = 443
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        try:
            with socket.create_connection((host, port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert(binary_form=True)
                    cert_obj = x509.load_der_x509_certificate(cert)

                    not_after = cert_obj.not_valid_after_utc
                    now = datetime.datetime.now(datetime.timezone.utc)
                    days_remaining = (not_after - now).days

                    return {
                        "success": True,
                        "expiry": not_after.strftime("%Y-%m-%d"),
                        "days_remaining": days_remaining,
                        "subject": cert_obj.subject.rfc4514_string(),
                        "issuer": cert_obj.issuer.rfc4514_string(),
                    }
        except Exception as e:
            self.logger.error(f"SSL check failed for {host}: {e}")
            return {"success": False, "message": str(e)}
