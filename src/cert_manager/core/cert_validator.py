"""X.509 certificate parsing and validation utilities."""

import datetime
import logging

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

logger = logging.getLogger("cert_manager.validator")


def load_cert(data: bytes) -> x509.Certificate | None:
    """Loads a PEM-encoded X.509 certificate."""
    try:
        return x509.load_pem_x509_certificate(data)
    except Exception as e:
        logger.error(f"Failed to load certificate: {e}")
        return None


def load_key(data: bytes) -> rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | None:
    """Loads a PEM-encoded private key."""
    try:
        return serialization.load_pem_private_key(data, password=None)
    except Exception as e:
        logger.error(f"Failed to load private key: {e}")
        return None


def validate_key_match(
    cert_obj: x509.Certificate,
    key_obj: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey,
) -> bool:
    """Checks if the private key matches the certificate's public key."""
    try:
        pub_key = cert_obj.public_key()
        if isinstance(key_obj, rsa.RSAPrivateKey):
            return key_obj.public_key().public_numbers() == pub_key.public_numbers()
        if isinstance(key_obj, ec.EllipticCurvePrivateKey):
            return key_obj.public_key().public_numbers() == pub_key.public_numbers()
        return False
    except Exception as e:
        logger.error(f"Key match validation failed: {e}")
        return False


def get_cert_details(cert_obj: x509.Certificate) -> dict:
    """Extracts subject, issuer, expiry, SANs from a certificate."""
    try:
        not_after = cert_obj.not_valid_after_utc
        not_before = cert_obj.not_valid_before_utc
        now = datetime.datetime.now(datetime.timezone.utc)
        days_remaining = (not_after - now).days

        sans: list[str] = []
        try:
            ext = cert_obj.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            sans = ext.value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            pass

        # Fall back to CN from subject if no SANs present
        if not sans:
            for attr in cert_obj.subject:
                if attr.oid == x509.oid.NameOID.COMMON_NAME:
                    sans = [attr.value]
                    break

        return {
            "subject": cert_obj.subject.rfc4514_string(),
            "issuer": cert_obj.issuer.rfc4514_string(),
            "serial_number": format(cert_obj.serial_number, "X"),
            "signature_algorithm": cert_obj.signature_algorithm_oid._name,
            "not_before": not_before.isoformat(),
            "not_after": not_after.isoformat(),
            "days_remaining": days_remaining,
            "sans": sans,
        }
    except Exception as e:
        logger.error(f"Failed to parse certificate details: {e}")
        return {}


def get_chain_details(data: bytes) -> list[dict]:
    """Parses all certificates in a PEM chain and returns details for each."""
    try:
        certs = x509.load_pem_x509_certificates(data)
        return [get_cert_details(c) for c in certs]
    except Exception as e:
        logger.error(f"Failed to load chain details: {e}")
        return []


def count_chain(data: bytes) -> int:
    """Counts the number of certificates in a PEM chain."""
    try:
        return data.decode("utf-8").count("BEGIN CERTIFICATE")
    except Exception:
        return 0


def normalize_pem(data: bytes) -> bytes:
    """Ensures PEM data has correct trailing newline."""
    return (data.decode("utf-8").strip() + "\n").encode("utf-8")


def detect_key_type(cert_data: bytes) -> str:
    """Detects whether a certificate uses an RSA or ECC public key.

    Returns:
        'rsa', 'ecc', or 'unknown'.
    """
    cert_obj = load_cert(cert_data)
    if cert_obj is None:
        return "unknown"

    pub_key = cert_obj.public_key()
    if isinstance(pub_key, rsa.RSAPublicKey):
        return "rsa"
    if isinstance(pub_key, ec.EllipticCurvePublicKey):
        return "ecc"
    return "unknown"
