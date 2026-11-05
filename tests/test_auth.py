"""Sign-in page for the setup page and API."""

from cert_manager.auth import session_ok, session_token
from cert_manager.config import get_settings


def _enable(monkeypatch, password="s3cret", username="admin"):
    monkeypatch.setenv("ADMIN_PASSWORD", password)
    monkeypatch.setenv("ADMIN_USERNAME", username)
    get_settings.cache_clear()


def test_open_when_password_is_empty(app_client):
    response = app_client.get("/api/certs")
    assert response.status_code == 200
    assert app_client.get("/login", follow_redirects=False).headers["location"] == "/"


def test_browser_is_sent_to_the_login_page(app_client, monkeypatch):
    _enable(monkeypatch)
    page = app_client.get("/", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/login?next=")
    assert "www-authenticate" not in page.headers

    login = app_client.get("/login")
    assert login.status_code == 200
    assert "Sign in" in login.text
    assert 'value="admin"' in login.text
    assert "DNS provider" not in login.text

    api = app_client.get("/api/certs")
    assert api.status_code == 401
    assert api.json()["detail"] == "Authentication required."
    assert "www-authenticate" not in api.headers
    assert app_client.get("/docs", follow_redirects=False).status_code == 303
    assert app_client.get("/openapi.json").status_code == 401


def test_login_sets_a_cookie_and_opens_the_page(app_client, monkeypatch):
    _enable(monkeypatch)
    signed = app_client.post(
        "/login",
        data={"username": "admin", "password": "s3cret", "next": "/"},
        follow_redirects=False,
    )
    assert signed.status_code == 303
    assert signed.headers["location"] == "/"
    assert "s3cret" not in signed.headers.get("set-cookie", "")
    page = app_client.get("/")
    assert page.status_code == 200
    assert "DNS provider" in page.text
    assert "Log out" in page.text
    certs = app_client.get("/api/certs")
    assert certs.status_code == 200
    health = app_client.get("/api/health")
    assert health.json()["auth_required"] is True


def test_wrong_username_or_password_is_rejected(app_client, monkeypatch):
    _enable(monkeypatch, username="ops")
    bad_user = app_client.post(
        "/login",
        data={"username": "admin", "password": "s3cret"},
        follow_redirects=False,
    )
    assert bad_user.status_code == 401
    assert "set-cookie" not in bad_user.headers
    assert "s3cret" not in bad_user.text
    assert "wrong" in bad_user.text
    bad_password = app_client.post(
        "/login",
        data={"username": "ops", "password": "nope"},
        follow_redirects=False,
    )
    assert bad_password.status_code == 401
    assert "nope" not in bad_password.text
    good = app_client.post(
        "/login",
        data={"username": "ops", "password": "s3cret", "next": "https://evil.example"},
        follow_redirects=False,
    )
    assert good.status_code == 303
    assert good.headers["location"] == "/"


def test_blank_username_stays_admin(app_client, monkeypatch):
    _enable(monkeypatch, username="  ")
    login = app_client.get("/login")
    assert 'value="admin"' in login.text
    signed = app_client.post(
        "/login",
        data={"username": "admin", "password": "s3cret"},
        follow_redirects=False,
    )
    assert signed.status_code == 303


def test_logout_clears_the_session(app_client, monkeypatch):
    _enable(monkeypatch)
    app_client.post("/login", data={"username": "admin", "password": "s3cret"})
    assert app_client.get("/api/certs").status_code == 200
    out = app_client.post("/logout", follow_redirects=False)
    assert out.status_code == 303
    assert out.headers["location"] == "/login"
    assert app_client.get("/api/certs").status_code == 401


def test_health_and_download_stay_open(app_client, monkeypatch):
    _enable(monkeypatch)
    health = app_client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["auth_required"] is True
    download = app_client.get("/download/missing-token/clearpass.pfx")
    assert download.status_code == 404
    assert "s3cret" not in download.text


def test_session_cookie_expires_and_follows_the_password():
    token = session_token("admin", "s3cret", now=1_000)
    assert session_ok(token, "admin", "s3cret", now=1_000 + 60)
    assert session_ok(token, "admin", "s3cret", now=1_000 + 12 * 60 * 60) is False
    assert session_ok(token, "admin", "other-password", now=1_000 + 60) is False
    assert session_ok(token, "someone", "s3cret", now=1_000 + 60) is False
