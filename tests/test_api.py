"""Tests for FastAPI REST API endpoints."""


class TestHealthEndpoint:
    def test_returns_healthy(self, app_client):
        r = app_client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "total_cert_packs" in data
        assert "total_services" in data

    def test_scheduler_disabled(self, app_client):
        r = app_client.get("/api/health")
        assert r.json()["scheduler_running"] is False


class TestCertEndpoints:
    def test_list_empty(self, app_client):
        r = app_client.get("/api/certs")
        assert r.status_code == 200
        assert r.json() == []

    def test_get_nonexistent(self, app_client):
        r = app_client.get("/api/certs/nope")
        assert r.status_code == 404

    def test_upload_stores_a_matching_pair(self, app_client):
        from tests.test_cert_validator import _generate_self_signed

        cert_pem, key_pem, _, _ = _generate_self_signed(sans=["clearpass.example.com"])
        r = app_client.post(
            "/api/certs/upload",
            json={
                "pack_name": "owned",
                "fullchain": cert_pem.decode(),
                "privkey": key_pem.decode(),
                "is_edge": False,
            },
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        pack = next(item for item in app_client.get("/api/certs").json() if item["name"] == "owned")
        assert pack["source"] == "manual"
        assert pack["auto_renew"] is False
        assert "clearpass.example.com" in pack["domains"]

    def test_upload_rejects_a_mismatched_key(self, app_client):
        from tests.test_cert_validator import _generate_self_signed

        cert_pem, _, _, _ = _generate_self_signed()
        _, other_key, _, _ = _generate_self_signed()
        r = app_client.post(
            "/api/certs/upload",
            json={
                "pack_name": "owned",
                "fullchain": cert_pem.decode(),
                "privkey": other_key.decode(),
                "is_edge": False,
            },
        )
        assert r.status_code == 200
        assert r.json()["success"] is False
        assert "does not match" in r.json()["message"]
        assert app_client.get("/api/certs").json() == []


class TestServiceEndpoints:
    def test_list_empty(self, app_client):
        r = app_client.get("/api/services")
        assert r.status_code == 200
        assert r.json() == []

    def test_add_service(self, app_client):
        r = app_client.post(
            "/api/services",
            json={
                "name": "test-svc",
                "host": "cp.example.com",
                "type": "clearpass",
                "cert_usage": "HTTPS(RSA)",
            },
        )
        assert r.status_code == 200
        assert r.json()["name"] == "test-svc"

    def test_get_service(self, app_client):
        app_client.post(
            "/api/services",
            json={
                "name": "get-me",
                "host": "cp.example.com",
                "type": "clearpass",
                "cert_usage": "HTTPS(RSA)",
            },
        )
        r = app_client.get("/api/services/get-me")
        assert r.status_code == 200
        assert r.json()["host"] == "cp.example.com"

    def test_get_nonexistent(self, app_client):
        r = app_client.get("/api/services/ghost")
        assert r.status_code == 404

    def test_delete_service(self, app_client):
        app_client.post(
            "/api/services",
            json={
                "name": "del-me",
                "host": "h",
                "type": "clearpass",
                "cert_usage": "HTTPS(RSA)",
            },
        )
        r = app_client.delete("/api/services/del-me")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_delete_nonexistent(self, app_client):
        r = app_client.delete("/api/services/ghost")
        assert r.status_code == 404


class TestCredentialEndpoints:
    def test_add_and_list_acme(self, app_client):
        r = app_client.post(
            "/api/credentials/acme",
            json={
                "id": "cf-test",
                "name": "Cloudflare Test",
                "provider": "cloudflare",
                "api_token": "test-token",
                "email": "test@example.com",
            },
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

        r = app_client.get("/api/credentials/acme")
        assert r.status_code == 200
        creds = r.json()
        assert any(c["id"] == "cf-test" for c in creds)

    def test_delete_acme(self, app_client):
        app_client.post(
            "/api/credentials/acme",
            json={
                "id": "del-cred",
                "name": "Delete Me",
                "provider": "cloudflare",
            },
        )
        r = app_client.delete("/api/credentials/acme/del-cred")
        assert r.status_code == 200

    def test_replacing_provider_drops_the_previous_secret(self, app_client):
        from cert_manager.api import routes

        app_client.post(
            "/api/credentials/acme",
            json={
                "id": "dns",
                "name": "Cloudflare",
                "provider": "cloudflare",
                "api_token": "cf-token-value",
            },
        )
        r = app_client.post(
            "/api/credentials/acme",
            json={
                "id": "dns",
                "name": "Route 53",
                "provider": "route53",
                "access_key_id": "AKIAEXAMPLE",
                "secret_access_key": "aws-secret-value",
            },
        )
        assert r.status_code == 200
        stored = routes._app_context["config"].get_acme_credential("dns")
        assert stored["provider"] == "route53"
        assert stored["access_key_id"] == "AKIAEXAMPLE"
        assert stored["secret_access_key"] == "aws-secret-value"
        assert "api_token" not in stored
        listed = app_client.get("/api/credentials/acme").text
        assert "aws-secret-value" not in listed
        assert "cf-token-value" not in listed

    def test_add_and_list_clearpass(self, app_client):
        r = app_client.post(
            "/api/credentials/clearpass",
            json={
                "id": "cp-test",
                "name": "ClearPass Test",
                "host": "cp.example.com",
                "client_id": "cid",
                "client_secret": "csec",
            },
        )
        assert r.status_code == 200

        r = app_client.get("/api/credentials/clearpass")
        saved = next(c for c in r.json() if c["id"] == "cp-test")
        assert saved["host"] == "cp.example.com"
        assert saved["additional_nodes"] == []

    def test_clearpass_credential_keeps_subscriber_hosts(self, app_client):
        app_client.post(
            "/api/credentials/clearpass",
            json={
                "id": "cp-cluster",
                "name": "Cluster",
                "host": "cppm-node1.example.com",
                "client_id": "cid",
                "client_secret": "csec",
                "additional_nodes": ["cppm-node2.example.com", "cppm-node3.example.com"],
            },
        )
        r = app_client.get("/api/credentials/clearpass")
        saved = next(c for c in r.json() if c["id"] == "cp-cluster")
        assert saved["additional_nodes"] == ["cppm-node2.example.com", "cppm-node3.example.com"]
        assert "csec" not in r.text

    def test_delete_clearpass(self, app_client):
        app_client.post(
            "/api/credentials/clearpass",
            json={
                "id": "cp-del",
                "name": "Del",
                "host": "h",
                "client_id": "c",
                "client_secret": "s",
            },
        )
        r = app_client.delete("/api/credentials/clearpass/cp-del")
        assert r.status_code == 200


class TestSettingsEndpoints:
    def test_get_settings(self, app_client):
        r = app_client.get("/api/settings")
        assert r.status_code == 200

    def test_update_settings(self, app_client):
        r = app_client.patch("/api/settings", json={"log_level": "DEBUG"})
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestProvidersEndpoint:
    def test_list_providers(self, app_client):
        r = app_client.get("/api/providers/acme")
        assert r.status_code == 200
        providers = r.json()
        ids = [p["id"] for p in providers]
        assert "cloudflare" in ids
        assert "standalone" in ids


class TestSetupPage:
    def test_root_serves_setup_page(self, app_client):
        r = app_client.get("/", follow_redirects=False)
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "Cloudflare" in r.text
        assert "DNS provider" in r.text
        assert "DigitalOcean" in r.text
        assert "Route 53" in r.text
        assert "Generate New Token" in r.text
        assert "hosted zone" in r.text
        assert "cf-saved" not in r.text
        assert "provider: dns.provider" in r.text
        assert "credential_id: dns.id" in r.text
        assert "body.access_key_id" in r.text
        assert "body.secret_access_key" in r.text
        assert '$("dns-secret-key").value = ""' in r.text
        assert "Save a Cloudflare token." not in r.text
        assert "ClearPass" in r.text
        assert "Issue and install" in r.text
        assert "<details" in r.text
        assert 'id="cp-certs"' in r.text
        assert 'id="callback"' in r.text
        assert "Set EDGE_DOMAIN in the .env file" in r.text
        assert "Deploy" in r.text
        assert "Other cluster nodes" in r.text
        assert "Save and install" in r.text

    def test_docs_remain_available(self, app_client):
        r = app_client.get("/docs", follow_redirects=False)
        assert r.status_code == 200

    def test_health_reports_callback_base(self, app_client, monkeypatch):
        monkeypatch.setenv("EDGE_DOMAIN", "certs.example.com")
        r = app_client.get("/api/health")
        assert r.json()["callback_base"] == "http://certs.example.com"


class _Resp:
    """Minimal requests response for connection-test fakes."""

    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text if text or body is None else str(body)

    def json(self):
        if isinstance(self._body, dict):
            return self._body
        raise ValueError("no json")


_CERT_REQUEST = {
    "pack_name": "my-domain",
    "domains": ["example.com"],
    "provider": "cloudflare",
    "credential_id": "cloudflare-main",
    "email": "admin@example.com",
    "challenge_type": "dns-01",
    "key_type": "ecdsa",
    "is_edge": False,
}


class TestCertJobs:
    def test_blocking_request_still_returns_result(self, app_client):
        from cert_manager.api import routes

        def fake(**kwargs):
            assert kwargs["pack_name"] == "my-domain"
            assert "progress_callback" not in kwargs
            return {
                "success": True,
                "message": "Certificate obtained and saved as 'my-domain'.",
                "pack_name": "my-domain",
            }

        routes._app_context["acme"].request_certificate = fake
        r = app_client.post("/api/certs/request", json=_CERT_REQUEST)
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert "my-domain" in r.json()["message"]

    def test_job_returns_pending_then_records_progress(self, app_client):
        from cert_manager.api import routes

        def fake(**kwargs):
            kwargs["progress_callback"]("waiting for DNS")
            return {
                "success": True,
                "message": "Certificate obtained and saved as 'my-domain'.",
            }

        routes._app_context["acme"].request_certificate = fake
        started = app_client.post("/api/certs/jobs", json=_CERT_REQUEST)
        assert started.status_code == 200
        body = started.json()
        assert body["status"] == "PENDING"
        assert body["kind"] == "request"
        assert body["progress"] == []

        polled = app_client.get(f"/api/certs/jobs/{body['job_id']}")
        assert polled.status_code == 200
        finished = polled.json()
        assert finished["status"] == "SUCCESS"
        assert finished["success"] is True
        assert "waiting for DNS" in finished["progress"]

        listed = app_client.get("/api/certs/jobs")
        assert listed.status_code == 200
        assert listed.json()[0]["job_id"] == body["job_id"]

    def test_job_records_exception(self, app_client):
        from cert_manager.api import routes

        def fake(**kwargs):
            raise RuntimeError("certbot missing")

        routes._app_context["acme"].request_certificate = fake
        started = app_client.post("/api/certs/jobs", json=_CERT_REQUEST)
        polled = app_client.get(f"/api/certs/jobs/{started.json()['job_id']}")
        assert polled.json()["status"] == "FAILED"
        assert "certbot missing" in polled.json()["message"]

    def test_second_job_for_same_pack_conflicts(self, app_client):
        from cert_manager.api import routes

        routes._app_context["jobs"].create("my-domain", "request")
        r = app_client.post("/api/certs/jobs", json=_CERT_REQUEST)
        assert r.status_code == 409
        assert "my-domain" in r.json()["detail"]

    def test_unknown_job(self, app_client):
        r = app_client.get("/api/certs/jobs/does-not-exist")
        assert r.status_code == 404

    def test_renew_job_rejects_manual_pack(self, app_client):
        from cert_manager.api import routes

        routes._app_context["config"].set_cert_pack_meta("uploaded", {"source": "manual"})
        r = app_client.post("/api/certs/uploaded/jobs")
        assert r.status_code == 400

    def test_renew_job_missing_pack(self, app_client):
        r = app_client.post("/api/certs/missing/jobs")
        assert r.status_code == 404

    def test_renew_job_reports_progress(self, app_client):
        from cert_manager.api import routes

        routes._app_context["config"].set_cert_pack_meta(
            "radius-cert",
            {"source": "acme", "domains": ["radius.example.com"]},
        )

        def fake(pack_name, progress_callback=None):
            progress_callback("renewing")
            return {"success": True, "message": "renewed"}

        routes._app_context["acme"].renew_certificate = fake
        started = app_client.post("/api/certs/radius-cert/jobs")
        assert started.json()["status"] == "PENDING"
        polled = app_client.get(f"/api/certs/jobs/{started.json()['job_id']}")
        assert polled.json()["status"] == "SUCCESS"
        assert polled.json()["kind"] == "renew"
        assert "renewing" in polled.json()["progress"]


class TestCredentialTests:
    def test_cloudflare_token_ok(self, app_client, monkeypatch):
        def fake_get(url, headers=None, params=None, timeout=None):
            assert headers["Authorization"] == "Bearer super-secret-token"
            if url.endswith("/user/tokens/verify"):
                return _Resp(200, {"success": True, "result": {"status": "active"}})
            if url.endswith("/zones"):
                return _Resp(
                    200,
                    {"success": True, "result": [{"id": "z1", "name": "example.com"}]},
                )
            if url.endswith("/dns_records"):
                return _Resp(200, {"success": True, "result": []})
            raise AssertionError(url)

        monkeypatch.setattr("cert_manager.acme.cloudflare.requests.get", fake_get)
        r = app_client.post(
            "/api/credentials/acme/test",
            json={"api_token": "super-secret-token"},
        )
        body = r.json()
        assert r.status_code == 200
        assert body["success"] is True
        assert "example.com" in body["message"]
        assert body["data"]["dns_read"] is True
        assert "super-secret-token" not in r.text

    def test_cloudflare_token_rejected(self, app_client, monkeypatch):
        monkeypatch.setattr(
            "cert_manager.acme.cloudflare.requests.get",
            lambda *args, **kwargs: _Resp(401, {"success": False}),
        )
        r = app_client.post("/api/credentials/acme/test", json={"api_token": "nope"})
        assert r.json()["success"] is False
        assert "rejected" in r.json()["message"]

    def test_saved_cloudflare_credential(self, app_client, monkeypatch):
        app_client.post(
            "/api/credentials/acme",
            json={
                "id": "cf-test",
                "name": "Cloudflare",
                "provider": "cloudflare",
                "api_token": "saved-token",
            },
        )

        def fake_get(url, headers=None, params=None, timeout=None):
            assert headers["Authorization"] == "Bearer saved-token"
            return _Resp(401, {"success": False})

        monkeypatch.setattr("cert_manager.acme.cloudflare.requests.get", fake_get)
        r = app_client.post("/api/credentials/acme/cf-test/test")
        assert r.status_code == 200
        assert r.json()["success"] is False
        assert "saved-token" not in r.text

    def test_non_cloudflare_credential_is_not_probed(self, app_client):
        app_client.post(
            "/api/credentials/acme",
            json={
                "id": "aws",
                "name": "AWS",
                "provider": "route53",
                "access_key_id": "AKIA",
                "secret_access_key": "secret",
            },
        )
        r = app_client.post("/api/credentials/acme/aws/test")
        assert r.json()["success"] is False
        assert "route53" in r.json()["message"]
        assert "secret" not in r.json()["message"]

    def test_digitalocean_token_ok(self, app_client, monkeypatch):
        def fake_get(url, headers=None, params=None, timeout=None):
            assert headers["Authorization"] == "Bearer do-secret-token"
            assert url == "https://api.digitalocean.com/v2/domains"
            return _Resp(
                200,
                {"domains": [{"name": "example.com"}], "meta": {"total": 1}},
            )

        monkeypatch.setattr("cert_manager.acme.digitalocean.requests.get", fake_get)
        r = app_client.post(
            "/api/credentials/acme/test",
            json={"provider": "digitalocean", "api_token": "do-secret-token"},
        )
        body = r.json()
        assert r.status_code == 200
        assert body["success"] is True
        assert "example.com" in body["message"]
        assert body["data"]["domains"] == ["example.com"]
        assert "do-secret-token" not in r.text

    def test_saved_digitalocean_credential(self, app_client, monkeypatch):
        app_client.post(
            "/api/credentials/acme",
            json={
                "id": "do-test",
                "name": "DigitalOcean",
                "provider": "digitalocean",
                "api_token": "do-saved-token",
            },
        )

        def fake_get(url, headers=None, params=None, timeout=None):
            assert headers["Authorization"] == "Bearer do-saved-token"
            return _Resp(200, {"domains": [{"name": "example.com"}]})

        monkeypatch.setattr("cert_manager.acme.digitalocean.requests.get", fake_get)
        r = app_client.post("/api/credentials/acme/do-test/test")
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert "do-saved-token" not in r.text

    def test_route53_inline_is_not_probed(self, app_client, monkeypatch):
        def boom(*args, **kwargs):
            raise AssertionError("DNS provider test called the network")

        monkeypatch.setattr("cert_manager.acme.cloudflare.requests.get", boom)
        monkeypatch.setattr("cert_manager.acme.digitalocean.requests.get", boom)
        r = app_client.post(
            "/api/credentials/acme/test",
            json={"provider": "route53", "api_token": "unused-token"},
        )
        assert r.json()["success"] is False
        assert "route53" in r.json()["message"]
        assert "unused-token" not in r.text

    def test_missing_acme_credential(self, app_client):
        r = app_client.post("/api/credentials/acme/missing/test")
        assert r.status_code == 404

    def test_clearpass_oauth_error_hides_secret(self, app_client, monkeypatch):
        def fake_post(url, json=None, **kwargs):
            assert json["client_secret"] == "s3cret"
            assert url == "https://clearpass.example.com/api/oauth"
            return _Resp(401, text='{"error":"invalid_client"}')

        monkeypatch.setattr("cert_manager.handlers.clearpass.requests.post", fake_post)
        r = app_client.post(
            "/api/credentials/clearpass/test",
            json={
                "host": "clearpass.example.com",
                "client_id": "cert-manager",
                "client_secret": "s3cret",
            },
        )
        body = r.json()
        assert body["success"] is False
        assert "401" in body["message"]
        assert "invalid_client" in body["message"]
        assert body["data"]["stage"] == "oauth"
        assert "s3cret" not in r.text

    def test_saved_clearpass_credential_lists_nodes(self, app_client, monkeypatch):
        app_client.post(
            "/api/credentials/clearpass",
            json={
                "id": "cp-test",
                "name": "Prod",
                "host": "cp.example.com",
                "client_id": "cid",
                "client_secret": "stored-secret",
            },
        )

        def fake_post(url, json=None, **kwargs):
            assert json["client_secret"] == "stored-secret"
            return _Resp(200, {"access_token": "tok"})

        def fake_get(url, headers=None, **kwargs):
            assert headers["Authorization"] == "Bearer tok"
            return _Resp(
                200,
                {"_embedded": {"items": [{"name": "cppm1", "server_uuid": "u1"}]}},
            )

        monkeypatch.setattr("cert_manager.handlers.clearpass.requests.post", fake_post)
        monkeypatch.setattr("cert_manager.handlers.clearpass.requests.get", fake_get)
        r = app_client.post("/api/credentials/clearpass/cp-test/test")
        body = r.json()
        assert body["success"] is True
        assert body["data"]["servers"] == ["cppm1"]
        certificates = body["data"]["certificates"]
        assert [row["label"] for row in certificates] == [
            "HTTPS (RSA)",
            "HTTPS (ECC)",
            "RADIUS / EAP",
            "RadSec",
            "Database",
        ]
        assert all(row["names"] == [] for row in certificates)
        assert "tok" not in r.text
        assert "stored-secret" not in r.text


class TestDeployResult:
    def test_deploy_returns_stage_and_message(self, app_client, monkeypatch):
        from cert_manager.api import routes
        from cert_manager.handlers.clearpass import ArubaClearPassHandler

        app_client.post(
            "/api/services",
            json={
                "name": "cppm",
                "host": "cp.example.com",
                "type": "clearpass",
                "cert_pack_id": "my-domain",
                "cert_usage": "HTTPS(RSA)",
            },
        )
        routes._app_context["cert_store"].get_pack_paths = lambda name: (
            "/tmp/fullchain.pem",
            "/tmp/privkey.pem",
        )

        def fake_deploy(self, cert_path, key_path):
            return {
                "success": False,
                "message": "ClearPass authentication failed (401): invalid_client",
                "stage": "oauth",
                "nodes": [
                    {
                        "host": "https://cp.example.com",
                        "success": False,
                        "stage": "oauth",
                        "message": "ClearPass authentication failed (401): invalid_client",
                    }
                ],
            }

        monkeypatch.setattr(ArubaClearPassHandler, "deploy", fake_deploy)
        r = app_client.post("/api/services/cppm/deploy")
        body = r.json()
        assert r.status_code == 200
        assert body["success"] is False
        assert body["data"]["stage"] == "oauth"
        assert "401" in body["message"]
        assert "invalid_client" in body["message"]
