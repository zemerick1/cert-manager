"""Tests for X.509 certificate validation utilities."""

import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from cert_manager.core import cert_validator


def _generate_self_signed(key_cls="rsa", days=90, cn="test.example.com", sans=None):
    """Helper to create a self-signed cert + key pair in PEM bytes."""
    if key_cls == "rsa":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    else:
        key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=days))
    )

    if sans:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]),
            critical=False,
        )

    cert = builder.sign(key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem, cert, key


class TestLoadCert:
    def test_valid_pem(self):
        cert_pem, _, _, _ = _generate_self_signed()
        obj = cert_validator.load_cert(cert_pem)
        assert obj is not None

    def test_invalid_pem(self):
        assert cert_validator.load_cert(b"not a cert") is None


class TestLoadKey:
    def test_valid_pem(self):
        _, key_pem, _, _ = _generate_self_signed()
        obj = cert_validator.load_key(key_pem)
        assert obj is not None

    def test_invalid_pem(self):
        assert cert_validator.load_key(b"not a key") is None


class TestKeyMatch:
    def test_matching_rsa(self):
        _, _, cert_obj, key_obj = _generate_self_signed("rsa")
        assert cert_validator.validate_key_match(cert_obj, key_obj) is True

    def test_matching_ec(self):
        _, _, cert_obj, key_obj = _generate_self_signed("ec")
        assert cert_validator.validate_key_match(cert_obj, key_obj) is True

    def test_mismatched(self):
        _, _, cert_obj, _ = _generate_self_signed("rsa")
        _, _, _, other_key = _generate_self_signed("rsa")
        assert cert_validator.validate_key_match(cert_obj, other_key) is False


class TestGetCertDetails:
    def test_extracts_fields(self):
        cert_pem, _, cert_obj, _ = _generate_self_signed(
            cn="example.com", sans=["example.com", "*.example.com"]
        )
        details = cert_validator.get_cert_details(cert_obj)
        assert "example.com" in details["sans"]
        assert "*.example.com" in details["sans"]
        assert details["days_remaining"] > 0
        assert details["serial_number"]

    def test_falls_back_to_cn(self):
        _, _, cert_obj, _ = _generate_self_signed(cn="fallback.test")
        details = cert_validator.get_cert_details(cert_obj)
        assert details["sans"] == ["fallback.test"]


class TestDetectKeyType:
    def test_rsa(self):
        cert_pem, _, _, _ = _generate_self_signed("rsa")
        assert cert_validator.detect_key_type(cert_pem) == "rsa"

    def test_ecc(self):
        cert_pem, _, _, _ = _generate_self_signed("ec")
        assert cert_validator.detect_key_type(cert_pem) == "ecc"

    def test_invalid(self):
        assert cert_validator.detect_key_type(b"garbage") == "unknown"


class TestNormalizePem:
    def test_adds_trailing_newline(self):
        data = b"-----BEGIN CERTIFICATE-----\nABC\n-----END CERTIFICATE-----"
        result = cert_validator.normalize_pem(data)
        assert result.endswith(b"\n")
        assert not result.endswith(b"\n\n")

    def test_idempotent(self):
        data = b"-----BEGIN CERTIFICATE-----\nABC\n-----END CERTIFICATE-----\n"
        assert cert_validator.normalize_pem(data) == data


class TestCountChain:
    def test_single(self):
        cert_pem, _, _, _ = _generate_self_signed()
        assert cert_validator.count_chain(cert_pem) == 1

    def test_double(self):
        c1, _, _, _ = _generate_self_signed()
        c2, _, _, _ = _generate_self_signed()
        assert cert_validator.count_chain(c1 + c2) == 2
