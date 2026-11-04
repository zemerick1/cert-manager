"""Tests for structured ClearPass deploy results."""

import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import cert_manager.handlers.clearpass as clearpass
from cert_manager.handlers.clearpass import ArubaClearPassHandler


class _Resp:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text or ""

    def json(self):
        return self._body


def _handler():
    return ArubaClearPassHandler(
        {
            "name": "cppm",
            "host": "clearpass.example.com",
            "client_id": "cert-manager",
            "client_secret": "s3cret",
            "cert_usage": "HTTPS(RSA)",
        }
    )


def test_oauth_failure_names_the_status(monkeypatch):
    monkeypatch.setattr(
        clearpass,
        "_create_pfx",
        lambda *args, **kwargs: ("/tmp/missing-cert-manager.pfx", None),
    )

    def fake_post(url, json=None, **kwargs):
        return _Resp(401, text='{"error":"invalid_client"}')

    monkeypatch.setattr(clearpass.requests, "post", fake_post)
    result = _handler().deploy("/tmp/fullchain.pem", "/tmp/privkey.pem")
    assert result["success"] is False
    assert result["stage"] == "oauth"
    assert "401" in result["message"]
    assert "invalid_client" in result["message"]
    assert "s3cret" not in result["message"]


def test_install_rejection_includes_download_url(monkeypatch):
    monkeypatch.setenv("EDGE_DOMAIN", "certs.example.com")
    monkeypatch.setattr(
        clearpass,
        "_create_pfx",
        lambda *args, **kwargs: ("/tmp/missing-cert-manager.pfx", None),
    )
    monkeypatch.setattr(clearpass, "ensure_ca_trust", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        clearpass.requests,
        "post",
        lambda *args, **kwargs: _Resp(200, {"access_token": "tok"}),
    )
    monkeypatch.setattr(
        clearpass.requests,
        "get",
        lambda *args, **kwargs: _Resp(
            200,
            {"_embedded": {"items": [{"name": "cppm1", "server_uuid": "u1"}]}},
        ),
    )

    def fake_put(url, json=None, **kwargs):
        return _Resp(400, text="unable to download pkcs12")

    monkeypatch.setattr(clearpass.requests, "put", fake_put)
    result = _handler().deploy("/tmp/fullchain.pem", "/tmp/privkey.pem")
    assert result["success"] is False
    assert result["stage"] == "install"
    assert "400" in result["message"]
    assert "unable to download pkcs12" in result["message"]
    assert "http://certs.example.com/download/" in result["message"]
    assert result["nodes"][0]["servers"][0]["success"] is False


def test_ca_trust_error_stays_visible_when_install_succeeds(monkeypatch):
    monkeypatch.setattr(
        clearpass,
        "_create_pfx",
        lambda *args, **kwargs: ("/tmp/missing-cert-manager.pfx", None),
    )
    monkeypatch.setattr(
        clearpass,
        "ensure_ca_trust",
        lambda *args, **kwargs: ["Failed to add CA R3 [403]: denied"],
    )
    monkeypatch.setattr(
        clearpass.requests,
        "post",
        lambda *args, **kwargs: _Resp(200, {"access_token": "tok"}),
    )
    monkeypatch.setattr(
        clearpass.requests,
        "get",
        lambda *args, **kwargs: _Resp(
            200,
            {"_embedded": {"items": [{"name": "cppm1", "server_uuid": "u1"}]}},
        ),
    )
    monkeypatch.setattr(
        clearpass.requests,
        "put",
        lambda *args, **kwargs: _Resp(200, text="ok"),
    )
    result = _handler().deploy("/tmp/fullchain.pem", "/tmp/privkey.pem")
    assert result["success"] is True
    assert result["stage"] == "install"
    assert "Deployment successful" in result["message"]
    assert "Failed to add CA R3 [403]: denied" in result["message"]
    assert result["nodes"][0]["ca_trust_errors"] == ["Failed to add CA R3 [403]: denied"]


def test_missing_config_is_its_own_stage():
    handler = ArubaClearPassHandler({"name": "cppm", "host": "clearpass.example.com"})
    result = handler.deploy("/tmp/fullchain.pem", "/tmp/privkey.pem")
    assert result["success"] is False
    assert result["stage"] == "config"
    assert "client_id" in result["message"]


def _pem(sans: list[str] | None, cn: str) -> str:
    """Builds a self-signed PEM. DNS names come from the SANs, or the CN."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=30))
    )
    if sans:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(item) for item in sans]),
            critical=False,
        )
    cert = builder.sign(key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_connection_reports_installed_fqdns(monkeypatch, caplog):
    https_pem = _pem(["clearpass.example.com", "cppm.example.com"], "clearpass.example.com")
    other_pem = _pem(["other.example.com"], "other.example.com")
    database_pem = _pem(None, "db.example.com")

    def fake_post(url, json=None, **kwargs):
        return _Resp(200, {"access_token": "tok"})

    def fake_get(url, headers=None, **kwargs):
        if url.endswith("/api/cluster/server"):
            return _Resp(
                200,
                {
                    "_embedded": {
                        "items": [
                            {"name": "cppm1", "server_uuid": "u1"},
                            {"name": "cppm2", "server_uuid": "u2"},
                        ]
                    }
                },
            )
        if url.endswith("/u1/HTTPS(RSA)"):
            return _Resp(200, {"cert_file": https_pem})
        if url.endswith("/u2/HTTPS(RSA)"):
            return _Resp(200, {"cert_file": other_pem})
        if url.endswith("/Database"):
            return _Resp(200, {"cert_file": database_pem})
        return _Resp(404, text="not found")

    monkeypatch.setattr(clearpass.requests, "post", fake_post)
    monkeypatch.setattr(clearpass.requests, "get", fake_get)
    result = _handler().test_connection()

    assert result["success"] is True
    certificates = result["data"]["certificates"]
    assert [row["usage"] for row in certificates] == [
        "HTTPS(RSA)",
        "HTTPS(ECC)",
        "RADIUS",
        "RadSec",
        "Database",
    ]
    https = certificates[0]
    assert https["label"] == "HTTPS (RSA)"
    assert https["names"] == ["clearpass.example.com", "cppm.example.com", "other.example.com"]
    assert https["servers"][0]["names"] == ["clearpass.example.com", "cppm.example.com"]
    assert https["servers"][1] == {"server": "cppm2", "names": ["other.example.com"]}
    assert certificates[1]["names"] == []
    assert certificates[2]["label"] == "RADIUS / EAP"
    assert certificates[3]["label"] == "RadSec"
    assert certificates[4]["label"] == "Database"
    assert certificates[4]["names"] == ["db.example.com"]
    assert "API cert lookup failed" not in caplog.text
    assert "tok" not in result["message"]
