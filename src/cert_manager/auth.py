"""Sign-in page session for the setup page and API.

The browser posts the username and password to /login and keeps a signed
cookie. ClearPass downloads a certificate from /download without that
cookie. The one-time token in that URL is the credential. /api/health
stays open so the container health check does not need a session.
"""

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import time
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from cert_manager.config import Settings, get_settings

logger = logging.getLogger("cert_manager.auth")

COOKIE = "cm_session"
SESSION_SECONDS = 12 * 60 * 60
_LOGIN_FILE = os.path.join(os.path.dirname(__file__), "static", "login.html")


def password_value(settings: Settings | None = None) -> str:
    """Returns the configured password with surrounding whitespace removed."""
    settings = settings or get_settings()
    return (settings.admin_password or "").strip()


def auth_enabled(settings: Settings | None = None) -> bool:
    """Returns True when a password is configured."""
    return bool(password_value(settings))


def expected_username(settings: Settings | None = None) -> str:
    """Returns the login name. An empty value stays admin."""
    settings = settings or get_settings()
    name = (settings.admin_username or "").strip()
    return name or "admin"


def is_public_path(path: str) -> bool:
    """Returns True for routes that must answer without a session."""
    if path in ("/login", "/logout"):
        return True
    if path == "/api/health" or path.startswith("/api/health/"):
        return True
    return path == "/download" or path.startswith("/download/")


def login_ok(username: str, password: str, settings: Settings | None = None) -> bool:
    """Returns True when the submitted login matches the configured one."""
    expected_pass = password_value(settings)
    if not expected_pass:
        return False
    user_ok = secrets.compare_digest(username, expected_username(settings))
    password_ok = secrets.compare_digest(password, expected_pass)
    return user_ok and password_ok


def safe_next(value: str | None) -> str:
    """Returns a same-site path to open after sign-in."""
    raw = (value or "").strip()
    if not raw.startswith("/") or raw.startswith("//") or raw.split("?", 1)[0] == "/login":
        return "/"
    if "\\" in raw or "://" in raw or any(ord(ch) < 32 for ch in raw):
        return "/"
    return raw


def session_token(username: str, password: str, now: float | None = None) -> str:
    """Returns a signed cookie value that expires SESSION_SECONDS from now."""
    expiry = int(now if now is not None else time.time()) + SESSION_SECONDS
    body = _body(username, expiry)
    return f"{body}.{_sign(body, password)}"


def session_ok(token: str, username: str, password: str, now: float | None = None) -> bool:
    """Returns True when the cookie is signed, unexpired, and for this login."""
    if not token or "." not in token or not password:
        return False
    body, sig = token.rsplit(".", 1)
    if not secrets.compare_digest(sig, _sign(body, password)):
        return False
    parsed = _parse_body(body)
    if parsed is None:
        return False
    given_user, expiry = parsed
    if not secrets.compare_digest(given_user, username):
        return False
    current = int(now if now is not None else time.time())
    return expiry > current


def request_authenticated(request: Request, settings: Settings | None = None) -> bool:
    """Returns True when auth is off or the request has a valid session cookie."""
    settings = settings or get_settings()
    password = password_value(settings)
    if not password:
        return True
    token = request.cookies.get(COOKIE, "")
    return session_ok(token, expected_username(settings), password)


def attach_session(response: Response, settings: Settings | None = None) -> None:
    """Sets the sign-in cookie on a response. The password is not stored."""
    settings = settings or get_settings()
    token = session_token(expected_username(settings), password_value(settings))
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    """Removes the sign-in cookie."""
    response.delete_cookie(COOKIE, path="/")


def login_page(
    username: str,
    next_path: str,
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    """Renders the sign-in page. The password is never written into the HTML."""
    error_html = ""
    if error:
        error_html = f'<p class="result bad">{html.escape(error)}</p>'
    page = _login_template()
    page = page.replace("__USERNAME__", html.escape(username, quote=True))
    page = page.replace("__NEXT__", html.escape(safe_next(next_path), quote=True))
    page = page.replace("__ERROR__", error_html)
    return HTMLResponse(page, status_code=status_code)


class AdminAuthMiddleware:
    """Sends browsers to the sign-in page. API calls without a session get 401.

    This is raw ASGI so a login POST body still reaches the route.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        settings = get_settings()
        path = request.url.path
        if password_value(settings) and not is_public_path(path):
            if not request_authenticated(request, settings):
                response = _reject(request)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _reject(request: Request) -> Response:
    """Returns the 401 or the redirect to the sign-in page."""
    path = request.url.path
    if path.startswith("/api") or path == "/openapi.json":
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    target = path
    if request.url.query:
        target = f"{path}?{request.url.query}"
    location = "/login?next=" + quote(safe_next(target), safe="")
    return RedirectResponse(location, status_code=303)


def log_auth_mode(settings: Settings | None = None) -> None:
    """Logs whether the sign-in page is on. The password is not logged."""
    settings = settings or get_settings()
    if auth_enabled(settings):
        logger.info("Sign-in page is on for user %s.", expected_username(settings))
        return
    logger.warning("ADMIN_PASSWORD is empty. The setup page and API are open.")


def _body(username: str, expiry: int) -> str:
    raw = json.dumps({"u": username, "e": expiry}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _parse_body(body: str) -> tuple[str, int] | None:
    padded = body + "=" * (-len(body) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    username = data.get("u")
    expiry = data.get("e")
    if not isinstance(username, str) or isinstance(expiry, bool) or not isinstance(expiry, int):
        return None
    return username, expiry


def _sign(body: str, password: str) -> str:
    digest = hmac.new(password.encode(), body.encode(), hashlib.sha256).hexdigest()
    return digest


def _login_template() -> str:
    with open(_LOGIN_FILE, encoding="utf-8") as handle:
        return handle.read()
