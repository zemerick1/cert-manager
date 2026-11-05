"""FastAPI application - serves REST API and PFX download endpoints."""

import logging
import logging.handlers
import os
import subprocess
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from cert_manager.acme.manager import AcmeManager
from cert_manager.api.routes import router, set_context
from cert_manager.auth import (
    AdminAuthMiddleware,
    attach_session,
    auth_enabled,
    clear_session,
    expected_username,
    log_auth_mode,
    login_ok,
    login_page,
    request_authenticated,
    safe_next,
)
from cert_manager.config import get_settings
from cert_manager.core.cert_store import CertStore
from cert_manager.core.config_manager import ConfigManager
from cert_manager.handlers.clearpass import get_download_path
from cert_manager.services.cert_jobs import CertJobStore
from cert_manager.services.scheduler import RenewalScheduler

logger = logging.getLogger("cert_manager")

# Global app context
_app_context: dict = {}


def _setup_logging() -> str | None:
    """Configures structured logging to console and optional file."""
    settings = get_settings()
    log_dir = os.path.join(settings.data_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "cert-manager.log")

    root_logger = logging.getLogger("cert_manager")
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(
        logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
        )
    )
    root_logger.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root_logger.addHandler(file_handler)

    return log_path


def _ensure_edge_cert_exists() -> None:
    """Ensures nginx can find an SSL certificate at the EDGE_DOMAIN path."""
    settings = get_settings()
    domain = settings.edge_domain or "localhost"
    cert_dir = os.path.join(settings.ssl_dir, "live", domain)
    fullchain = os.path.join(cert_dir, "fullchain.pem")
    privkey = os.path.join(cert_dir, "privkey.pem")

    # Check if an ACME pack exists that should be linked to the edge domain.
    if _app_context.get("cert_store") and _app_context.get("config"):
        cert_store = _app_context["cert_store"]
        config = _app_context["config"]
        for pack_name, meta in config.get_cert_packs_meta().items():
            if meta.get("is_edge") and pack_name != domain:
                pack_dir = os.path.join(settings.ssl_dir, "live", pack_name)
                if os.path.isdir(pack_dir) and not os.path.islink(pack_dir):
                    cert_store._link_edge_domain(pack_name)
                    logger.info(f"Linked existing ACME pack '{pack_name}' to edge domain.")
                    return

    if os.path.isfile(fullchain) and os.path.isfile(privkey):
        logger.info(f"Edge certificate exists for {domain}.")
        return

    # Clean up directory stubs left by Docker bind mounts
    for path in (fullchain, privkey):
        if os.path.isdir(path):
            os.rmdir(path)

    logger.info(f"No edge certificate found - generating self-signed for {domain}.")
    # Remove dangling symlinks left when an edge cert pack is deleted
    if os.path.islink(cert_dir) and not os.path.exists(cert_dir):
        os.remove(cert_dir)
    os.makedirs(cert_dir, exist_ok=True)

    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-days",
            "1",
            "-keyout",
            privkey,
            "-out",
            fullchain,
            "-subj",
            f"/CN={domain}/O=Self-Signed",
        ],
        check=True,
        capture_output=True,
    )
    os.chmod(privkey, 0o644)

    marker = os.path.join(cert_dir, ".placeholder")
    with open(marker, "w") as f:
        f.write("self-signed placeholder for nginx startup\n")

    logger.info("Self-signed placeholder certificate generated (valid 1 day).")


async def _nginx_reload_callback() -> None:
    """Async callback for scheduler to reload nginx."""
    from cert_manager.services.nginx_reload import reload_nginx

    await reload_nginx()


async def _deploy_to_services_for_pack(pack_name: str) -> None:
    """Deploys a renewed cert to all services that reference this pack."""
    import asyncio

    from cert_manager.handlers.clearpass import ArubaClearPassHandler

    ctx = _app_context
    services = ctx["config"].get_services()
    for service in services:
        if service.get("cert_pack_id") == pack_name and service.get("enabled", True):
            try:
                paths = ctx["cert_store"].get_pack_paths(pack_name)
                if paths:
                    # Get ClearPass credentials
                    cred_id = service.get("credential_id")
                    if cred_id:
                        cred = ctx["config"].get_clearpass_credential(cred_id)
                        if cred:
                            service["client_id"] = cred.get("client_id")
                            service["client_secret"] = cred.get("client_secret")

                    handler = ArubaClearPassHandler(service)
                    result = await asyncio.to_thread(handler.deploy, paths[0], paths[1])
                    if result.get("success"):
                        logger.info(
                            f"Auto-deployed '{pack_name}' to '{service['name']}': "
                            f"{result.get('message')}"
                        )
                    else:
                        logger.error(
                            f"Auto-deploy to '{service['name']}' failed: {result.get('message')}"
                        )
            except Exception as e:
                logger.error(f"Auto-deploy to '{service['name']}' failed: {e}")


def _check_service_health_sync(service: dict) -> str:
    """Sync health check function for the scheduler to call in a thread."""
    from cert_manager.handlers.clearpass import ArubaClearPassHandler

    # Get ClearPass credentials
    cred_id = service.get("credential_id")
    if cred_id:
        cred = _app_context["config"].get_clearpass_credential(cred_id)
        if cred:
            service["client_id"] = cred.get("client_id")
            service["client_secret"] = cred.get("client_secret")

    handler = ArubaClearPassHandler(service)
    result = handler.check_remote_expiry()

    # Check for cert mismatch
    if result.get("success"):
        pack_name = service.get("cert_pack_id")
        if pack_name:
            pack = _app_context["cert_store"].get_pack(
                pack_name, _app_context["config"].get_cert_packs_meta()
            )
            if pack and pack.get("serial_number") != result.get("serial_number"):
                return "Cert mismatch"
        return "Healthy"
    return result.get("message", "Unknown error")


def _initialize_context() -> None:
    """Initializes all application components and populates _app_context."""
    global _app_context

    log_path = _setup_logging()
    settings = get_settings()

    config_path = os.path.join(settings.data_dir, "config.yaml")
    certs_dir = os.path.join(settings.data_dir, "certs")

    config = ConfigManager(config_path)

    cert_store = CertStore(
        ssl_dir=settings.ssl_dir,
        certs_dir=certs_dir,
        edge_domain=settings.edge_domain,
    )

    acme = AcmeManager(
        config_manager=config,
        cert_store=cert_store,
        letsencrypt_dir=settings.ssl_dir,
    )

    scheduler = RenewalScheduler(
        acme_manager=acme,
        config_manager=config,
        cert_store=cert_store,
        nginx_reload_callback=_nginx_reload_callback,
        deploy_callback=_deploy_to_services_for_pack,
        health_check_fn=_check_service_health_sync,
    )

    _app_context = {
        "config": config,
        "cert_store": cert_store,
        "acme": acme,
        "scheduler": scheduler,
        "jobs": CertJobStore(),
        "edge_domain": settings.edge_domain,
        "log_path": log_path,
    }

    # Set context for route handlers
    set_context(_app_context)

    # Ensure edge certificate exists so nginx can start.
    _ensure_edge_cert_exists()

    logger.info("cert-manager initialized successfully.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - startup and shutdown."""
    _initialize_context()
    settings = get_settings()

    if settings.scheduler_enabled:
        _app_context["scheduler"].start()
    log_auth_mode(settings)

    yield

    if _app_context.get("scheduler"):
        _app_context["scheduler"].stop()


# --- Create FastAPI App ---

app = FastAPI(
    title="Certificate Manager",
    description="Standalone certificate lifecycle management with ACME and ClearPass deployment",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(AdminAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api")


# --- Additional Routes ---


@app.get("/download/{token}/{filename}")
async def download_pfx(token: str, filename: str):
    """One-time PFX file download endpoint for ClearPass callback."""
    file_path = get_download_path(token)

    if not file_path or not os.path.exists(file_path):
        return JSONResponse({"error": "Not found or expired"}, status_code=404)

    return FileResponse(
        file_path,
        media_type="application/x-pkcs12",
        filename="certificate.pfx",
    )


_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/")
async def root():
    """Serves the setup page. Interactive API documentation stays at /docs."""
    page = os.path.join(_STATIC_DIR, "index.html")
    if not os.path.isfile(page):
        return JSONResponse({"error": "Setup page is not installed"}, status_code=404)
    return FileResponse(page)


@app.get("/login")
async def login_form(request: Request, next_path: str = Query("/", alias="next")):
    """Shows the sign-in page. A valid session continues to the requested path."""
    settings = get_settings()
    destination = safe_next(next_path)
    if not auth_enabled(settings) or request_authenticated(request, settings):
        return RedirectResponse(destination if auth_enabled(settings) else "/", status_code=303)
    return login_page(expected_username(settings), destination)


@app.post("/login")
async def login_submit(request: Request):
    """Checks the sign-in form and sets the session cookie."""
    settings = get_settings()
    form = await request.form()
    destination = safe_next(str(form.get("next") or "/"))
    if not auth_enabled(settings):
        return RedirectResponse("/", status_code=303)
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    if not login_ok(username, password, settings):
        shown = username or expected_username(settings)
        return login_page(
            shown,
            destination,
            "That username or password is wrong.",
            status_code=401,
        )
    response = RedirectResponse(destination, status_code=303)
    attach_session(response, settings)
    logger.info("Sign-in succeeded for user %s.", expected_username(settings))
    return response


@app.post("/logout")
async def logout():
    """Clears the session cookie."""
    target = "/login" if auth_enabled() else "/"
    response = RedirectResponse(target, status_code=303)
    clear_session(response)
    return response
