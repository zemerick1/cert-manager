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
        assert any(c["id"] == "cp-test" for c in r.json())

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


class TestRootRedirect:
    def test_root_redirects_to_docs(self, app_client):
        r = app_client.get("/", follow_redirects=False)
        assert r.status_code == 307
        assert "/docs" in r.headers.get("location", "")
