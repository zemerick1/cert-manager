"""Aruba ClearPass certificate deployment handler.

Handles OAuth2 authentication, PFX generation, CA chain trust management,
and multi-node cluster certificate deployment.
"""

import datetime
import logging
import os
import secrets as secrets_module
import socket
import ssl
import string
import subprocess
import uuid

import requests
from cryptography import x509

from cert_manager.handlers.base import CertificateHandler
from cert_manager.handlers.clearpass_ca_trust import ensure_ca_trust

logger = logging.getLogger("cert_manager.handler.clearpass")

# Usage string mapping for ClearPass API
USAGE_MAP = {
    "https(rsa)": "HTTPS(RSA)",
    "https(ecc)": "HTTPS(ECC)",
    "radius": "RADIUS",
    "radsec": "RadSec",
    "database": "Database",
}

# CA trust list usage types required per certificate usage
CA_TRUST_USAGE_MAP = {
    "https(rsa)": ["Others"],
    "https(ecc)": ["Others"],
    "radius": ["EAP"],
    "radsec": ["RadSec"],
    "database": ["Database"],
}

# Module-level temp file registry for PFX downloads
_download_registry: dict[str, dict] = {}


def register_download(file_path: str, base_url: str) -> str | None:
    """Registers a PFX file for one-time download by ClearPass."""
    import time

    token = str(uuid.uuid4())
    _download_registry[token] = {
        "path": file_path,
        "expires": time.time() + 600,
    }
    return f"{base_url}/download/{token}/clearpass.pfx"


def get_download_path(token: str) -> str | None:
    """Retrieves and removes a registered download path (one-time use)."""
    import time

    entry = _download_registry.pop(token, None)
    if not entry:
        return None
    if time.time() > entry["expires"]:
        return None
    return entry["path"]


class ArubaClearPassHandler(CertificateHandler):
    """Deploys certificates to Aruba ClearPass via OAuth2 REST API."""

    def deploy(self, cert_path: str, key_path: str) -> bool:
        """Deploys certificate to all ClearPass nodes."""
        host, client_id, client_secret = self._parse_config()
        if not all([host, client_id, client_secret]):
            self.logger.error("Missing ClearPass config (host, client_id, client_secret)")
            return False

        pfx_password = self.config.get("pfx_password") or _generate_random_password()
        hosts = self._build_host_list(host)

        pfx_path = _create_pfx(cert_path, key_path, pfx_password)
        if not pfx_path:
            return False

        try:
            success_count = 0
            for current_host in hosts:
                self.logger.info(f"--- Processing Node: {current_host} ---")
                if self._deploy_to_node(
                    current_host,
                    client_id,
                    client_secret,
                    pfx_path,
                    pfx_password,
                    cert_path,
                ):
                    success_count += 1
            return success_count > 0
        finally:
            if os.path.exists(pfx_path):
                os.remove(pfx_path)

    def _deploy_to_node(
        self,
        host: str,
        client_id: str,
        client_secret: str,
        pfx_path: str,
        pfx_password: str,
        cert_path: str,
    ) -> bool:
        """Deploys certificate to a single ClearPass node."""
        try:
            token = _get_access_token(host, client_id, client_secret)
            if not token:
                self.logger.error(f"Failed to get token for {host}")
                return False

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            cert_usage = self.config.get("cert_usage", "https(rsa)").lower()
            ca_usages = CA_TRUST_USAGE_MAP.get(cert_usage, ["Others"])
            ensure_ca_trust(host, headers, cert_path, self.logger, ca_usages)

            server_uuids = _get_cluster_servers(host, headers, self.logger)
            if not server_uuids:
                return False

            usage = USAGE_MAP.get(
                self.config.get("cert_usage", "https(rsa)").lower(),
                self.config.get("cert_usage", "HTTPS(RSA)"),
            )
            edge_domain = os.environ.get("EDGE_DOMAIN", "localhost")
            callback_base = f"http://{edge_domain}"

            return _install_cert_on_servers(
                host,
                headers,
                server_uuids,
                usage,
                pfx_path,
                pfx_password,
                callback_base,
                self.logger,
            )
        except Exception as e:
            self.logger.error(f"Exception processing {host}: {e}")
            return False

    def check_remote_expiry(self) -> dict:
        """Checks ClearPass certificate status."""
        usage = self.config.get("cert_usage", "https(rsa)").lower()

        if usage.startswith("https"):
            return self._check_via_tls(usage)
        return self._check_via_api(usage)

    def _check_via_tls(self, usage: str) -> dict:
        """Checks ClearPass HTTPS cert using TLS cipher selection."""
        host = self.config.get("host")
        if not host:
            return {"success": False, "message": "No host configured"}

        if "://" in host:
            host = host.split("://", 1)[1]

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.maximum_version = ssl.TLSVersion.TLSv1_2

        if "ecc" in usage:
            context.set_ciphers("ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256")
        else:
            context.set_ciphers(
                "ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256:AES256-SHA:AES128-SHA"
            )

        try:
            with socket.create_connection((host, 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert(binary_form=True)
                    return _parse_cert_result(x509.load_der_x509_certificate(cert))
        except Exception as e:
            self.logger.error(f"ClearPass TLS check failed: {e}")
            return {"success": False, "message": str(e)}

    def _check_via_api(self, usage: str) -> dict:
        """Checks ClearPass cert for non-HTTPS types via REST API."""
        host, client_id, client_secret = self._parse_config()
        if not all([host, client_id, client_secret]):
            return {"success": False, "message": "Missing ClearPass credentials"}

        try:
            token = _get_access_token(host, client_id, client_secret)
            if not token:
                return {"success": False, "message": "Authentication failed"}

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            server_uuids = _get_cluster_servers(host, headers, self.logger)
            if not server_uuids:
                return {"success": False, "message": "No cluster servers found"}

            api_usage = USAGE_MAP.get(usage, self.config.get("cert_usage", "RADIUS"))
            first_uuid = next(iter(server_uuids.values()))

            return _get_cert_via_api(host, headers, first_uuid, api_usage, self.logger)
        except Exception as e:
            self.logger.error(f"ClearPass API cert check failed: {e}")
            return {"success": False, "message": str(e)}

    def _parse_config(self) -> tuple[str, str, str]:
        """Extracts host, client_id, client_secret from config."""
        host = self.config.get("host", "")
        if host and "://" not in host:
            host = f"https://{host}"
        return (
            host,
            self.config.get("client_id", ""),
            self.config.get("client_secret", ""),
        )

    def _build_host_list(self, primary_host: str) -> list[str]:
        """Builds list of all hosts including additional nodes."""
        hosts = [primary_host]
        additional = self.config.get("additional_nodes")
        if additional:
            if isinstance(additional, str):
                extra = [h.strip() for h in additional.split(",") if h.strip()]
            else:
                extra = [h.strip() for h in additional if h.strip()]
            for h in extra:
                hosts.append(f"https://{h}" if "://" not in h else h)
        return hosts


# --- Module-level helper functions ---


def _parse_cert_result(cert_obj: x509.Certificate) -> dict:
    """Extracts expiry, subject, issuer, and serial from a certificate."""
    not_after = cert_obj.not_valid_after_utc
    now = datetime.datetime.now(datetime.timezone.utc)
    days_remaining = (not_after - now).days

    return {
        "success": True,
        "expiry": not_after.strftime("%Y-%m-%d"),
        "days_remaining": days_remaining,
        "subject": cert_obj.subject.rfc4514_string(),
        "issuer": cert_obj.issuer.rfc4514_string(),
        "serial_number": format(cert_obj.serial_number, "x").upper(),
    }


def _get_cert_via_api(
    host: str,
    headers: dict,
    server_uuid: str,
    service_name: str,
    log: logging.Logger,
) -> dict:
    """Retrieves a certificate from ClearPass API and parses it."""
    url = f"{host}/api/server-cert/name/{server_uuid}/{service_name}"
    try:
        r = requests.get(url, headers=headers, verify=False, timeout=10)
        if r.status_code != 200:
            log.error(f"API cert lookup failed [{r.status_code}]: {r.text}")
            return {"success": False, "message": f"API returned {r.status_code}"}

        data = r.json()
        cert_pem = data.get("cert_file") or data.get("certificate")
        if not cert_pem:
            log.error(f"No cert_file in API response for {service_name}")
            return {"success": False, "message": "No certificate in API response"}

        cert_obj = x509.load_pem_x509_certificate(cert_pem.encode())
        return _parse_cert_result(cert_obj)
    except Exception as e:
        log.error(f"API cert check for {service_name} failed: {e}")
        return {"success": False, "message": str(e)}


def _generate_random_password() -> str:
    """Generates a 16-character alphanumeric password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets_module.choice(alphabet) for _ in range(16))


def _create_pfx(cert_path: str, key_path: str, pfx_password: str) -> str | None:
    """Creates a PKCS12/PFX bundle from cert and key files."""
    try:
        timestamp = uuid.uuid4().hex[:8]
        output_dir = os.path.dirname(cert_path)
        pfx_path = os.path.join(output_dir, f"clearpass_{timestamp}.pfx")

        cmd = [
            "openssl",
            "pkcs12",
            "-export",
            "-out",
            pfx_path,
            "-inkey",
            key_path,
            "-in",
            cert_path,
            "-passout",
            f"pass:{pfx_password}",
            "-legacy",
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return pfx_path
    except Exception as e:
        logger.error(f"PFX creation failed: {e}")
        return None


def _get_access_token(host: str, client_id: str, client_secret: str) -> str | None:
    """Obtains OAuth2 access token from ClearPass."""
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    try:
        r = requests.post(f"{host}/api/oauth", json=payload, verify=False, timeout=10)
        if r.status_code == 200:
            return r.json().get("access_token")
        logger.error(f"ClearPass auth failed: {r.text}")
        return None
    except Exception as e:
        logger.error(f"ClearPass auth exception: {e}")
        return None


def _get_cluster_servers(host: str, headers: dict, log: logging.Logger) -> dict[str, str]:
    """Fetches cluster server name->UUID mapping from ClearPass."""
    try:
        r = requests.get(f"{host}/api/cluster/server", headers=headers, verify=False, timeout=10)
        if r.status_code != 200:
            log.error(f"Failed to get cluster servers: {r.text}")
            return {}

        items = r.json().get("_embedded", {}).get("items", [])
        servers = {}
        for item in items:
            name = item.get("name")
            uuid_val = item.get("server_uuid")
            if name and uuid_val:
                servers[name] = uuid_val
        if not servers:
            log.error("No servers found in ClearPass cluster.")
        return servers
    except Exception as e:
        log.error(f"Cluster server lookup failed: {e}")
        return {}


def _install_cert_on_servers(
    host: str,
    headers: dict,
    server_uuids: dict[str, str],
    usage: str,
    pfx_path: str,
    pfx_password: str,
    callback_base: str,
    log: logging.Logger,
) -> bool:
    """Installs certificate on all cluster servers via download URL."""
    success_count = 0
    for name, uuid_val in server_uuids.items():
        download_url = register_download(pfx_path, callback_base)
        if not download_url:
            log.error(f"Failed to generate download URL for {name}")
            continue

        url = f"{host}/api/server-cert/name/{uuid_val}/{usage}"
        payload = {
            "pkcs12_file_url": download_url,
            "pkcs12_passphrase": pfx_password,
        }

        log.info(f"Updating {name} ({uuid_val}) usage {usage}, PFX URL: {download_url}")
        try:
            r = requests.put(url, json=payload, headers=headers, verify=False, timeout=30)
            if r.status_code == 200:
                log.info(f"Success for {name}")
                success_count += 1
            else:
                log.error(f"Failed for {name} [{r.status_code}]: {r.text}")
        except Exception as e:
            log.error(f"Exception updating {name}: {e}")

    return success_count > 0
