"""FastAPI route handlers for certificate management."""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from cert_manager.acme.cloudflare import test_cloudflare_token
from cert_manager.api.models import (
    AcmeCredential,
    AcmeCredentialInput,
    AppSettingsInput,
    CertJob,
    CertPack,
    CertRequestInput,
    CertUploadInput,
    ClearPassConnectionTestInput,
    ClearPassCredential,
    ClearPassCredentialInput,
    CloudflareTokenTestInput,
    HealthResponse,
    ManagedService,
    OperationResult,
    ServiceInput,
    ServiceUpdateInput,
)
from cert_manager.handlers.clearpass import ArubaClearPassHandler, get_callback_base
from cert_manager.services.cert_jobs import JobInProgress, run_renew_job, run_request_job

logger = logging.getLogger("cert_manager.api")

router = APIRouter()

# These will be injected via dependency injection
_app_context: dict = {}


def get_context() -> dict:
    """Returns the application context."""
    return _app_context


def set_context(ctx: dict) -> None:
    """Sets the application context (called at startup)."""
    global _app_context
    _app_context = ctx


Context = Annotated[dict, Depends(get_context)]


# --- Health ---


@router.get("/health", response_model=HealthResponse, tags=["Health"])
def health_check(ctx: Context):
    """Health check endpoint."""
    packs = ctx["cert_store"].list_packs(ctx["config"].get_cert_packs_meta())
    services = ctx["config"].get_services()
    expiring = [p for p in packs if (p.get("days_remaining") or 999) <= 30]
    scheduler = ctx.get("scheduler")

    return HealthResponse(
        status="healthy",
        scheduler_running=scheduler.is_running if scheduler else False,
        total_cert_packs=len(packs),
        total_services=len(services),
        certs_expiring_soon=len(expiring),
        next_renewal_check=(
            scheduler.next_check.isoformat() if scheduler and scheduler.next_check else None
        ),
        callback_base=get_callback_base(),
    )


# --- Certificate Packs ---


@router.get("/certs", response_model=list[CertPack], tags=["Certificates"])
def list_cert_packs(ctx: Context):
    """Lists all certificate packs."""
    packs = ctx["cert_store"].list_packs(ctx["config"].get_cert_packs_meta())
    return [CertPack(**p) for p in packs]


def _cert_request_fields(data: CertRequestInput) -> dict:
    """Maps a certificate request body onto AcmeManager.request_certificate."""
    return {
        "pack_name": data.pack_name,
        "domains": data.domains,
        "provider": data.provider.value,
        "credential_id": data.credential_id,
        "email": data.email,
        "challenge_type": data.challenge_type.value,
        "key_type": data.key_type.value,
        "is_edge": data.is_edge,
    }


@router.post("/certs/jobs", response_model=CertJob, tags=["Certificates"])
def start_cert_job(data: CertRequestInput, ctx: Context, background: BackgroundTasks):
    """Starts a certificate request and returns before Certbot finishes.

    Poll GET /certs/jobs/{job_id} for progress. POST /certs/request still
    waits for Certbot and returns the final result.
    """
    job = _create_job(ctx, data.pack_name, "request")
    background.add_task(
        run_request_job,
        ctx["jobs"],
        job["job_id"],
        ctx["acme"],
        _cert_request_fields(data),
    )
    return CertJob(**job)


@router.get("/certs/jobs", response_model=list[CertJob], tags=["Certificates"])
def list_cert_jobs(ctx: Context):
    """Lists certificate jobs started in this process, newest first."""
    return [CertJob(**job) for job in ctx["jobs"].list_jobs()]


@router.get("/certs/jobs/{job_id}", response_model=CertJob, tags=["Certificates"])
def get_cert_job(job_id: str, ctx: Context):
    """Returns one certificate job, including progress lines."""
    job = ctx["jobs"].get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Certificate job '{job_id}' not found")
    return CertJob(**job)


@router.post("/certs/{pack_name}/jobs", response_model=CertJob, tags=["Certificates"])
def start_renew_job(pack_name: str, ctx: Context, background: BackgroundTasks):
    """Starts a renewal and returns before Certbot finishes."""
    meta = ctx["config"].get_cert_pack_meta(pack_name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Certificate pack '{pack_name}' not found")
    if meta.get("source") != "acme":
        raise HTTPException(
            status_code=400,
            detail=f"Pack '{pack_name}' is not an ACME certificate.",
        )
    job = _create_job(ctx, pack_name, "renew")
    background.add_task(run_renew_job, ctx["jobs"], job["job_id"], ctx["acme"], pack_name)
    return CertJob(**job)


def _create_job(ctx: dict, pack_name: str, kind: str) -> dict:
    """Creates a job or raises 409 when one is already active for the pack."""
    try:
        return ctx["jobs"].create(pack_name, kind)
    except JobInProgress as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/certs/{pack_name}", response_model=CertPack, tags=["Certificates"])
def get_cert_pack(pack_name: str, ctx: Context):
    """Gets a specific certificate pack by name."""
    pack = ctx["cert_store"].get_pack(pack_name, ctx["config"].get_cert_packs_meta())
    if not pack:
        raise HTTPException(status_code=404, detail=f"Certificate pack '{pack_name}' not found")
    return CertPack(**pack)


@router.post("/certs/request", response_model=OperationResult, tags=["Certificates"])
def request_certificate(data: CertRequestInput, ctx: Context):
    """Requests a new ACME certificate from Let's Encrypt.

    This call blocks until Certbot finishes. POST /certs/jobs returns
    immediately and reports progress on GET /certs/jobs/{job_id}.
    """
    result = ctx["acme"].request_certificate(**_cert_request_fields(data))
    return OperationResult(**result)


@router.post("/certs/upload", response_model=OperationResult, tags=["Certificates"])
def upload_certificate(data: CertUploadInput, ctx: Context):
    """Uploads a manual certificate."""
    try:
        fullchain = data.fullchain.encode()
        privkey = data.privkey.encode()

        ctx["cert_store"].save_pack(
            name=data.pack_name,
            fullchain=fullchain,
            privkey=privkey,
            is_edge=data.is_edge,
        )

        # Save metadata
        ctx["config"].set_cert_pack_meta(
            data.pack_name,
            {
                "source": "manual",
                "is_edge": data.is_edge,
                "auto_renew": False,
            },
        )

        return OperationResult(
            success=True,
            message=f"Certificate uploaded as '{data.pack_name}'",
        )
    except Exception as e:
        logger.error(f"Certificate upload failed: {e}")
        return OperationResult(success=False, message=str(e))


@router.post("/certs/{pack_name}/renew", response_model=OperationResult, tags=["Certificates"])
def renew_certificate(pack_name: str, ctx: Context):
    """Renews an existing ACME certificate."""
    result = ctx["acme"].renew_certificate(pack_name)
    return OperationResult(**result)


@router.delete("/certs/{pack_name}", response_model=OperationResult, tags=["Certificates"])
def delete_cert_pack(pack_name: str, ctx: Context):
    """Deletes a certificate pack."""
    if ctx["cert_store"].delete_pack(pack_name):
        ctx["config"].delete_cert_pack_meta(pack_name)
        return OperationResult(success=True, message=f"Certificate pack '{pack_name}' deleted")
    raise HTTPException(status_code=404, detail=f"Certificate pack '{pack_name}' not found")


# --- Managed Services ---


@router.get("/services", response_model=list[ManagedService], tags=["Services"])
def list_services(ctx: Context):
    """Lists all managed services."""
    services = ctx["config"].get_services()
    return [ManagedService(**s) for s in services]


@router.get("/services/{service_name}", response_model=ManagedService, tags=["Services"])
def get_service(service_name: str, ctx: Context):
    """Gets a specific service by name."""
    service = ctx["config"].get_service(service_name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    return ManagedService(**service)


@router.post("/services", response_model=ManagedService, tags=["Services"])
def add_service(data: ServiceInput, ctx: Context):
    """Adds a new managed service."""
    try:
        service_data = data.model_dump()
        service_data["type"] = data.type.value
        service_data["cert_usage"] = data.cert_usage.value
        result = ctx["config"].add_service(service_data)
        return ManagedService(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/services/{service_name}", response_model=ManagedService, tags=["Services"])
def update_service(service_name: str, data: ServiceUpdateInput, ctx: Context):
    """Updates an existing service."""
    try:
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        if "cert_usage" in update_data:
            update_data["cert_usage"] = update_data["cert_usage"].value
        result = ctx["config"].update_service(service_name, update_data)
        return ManagedService(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/services/{service_name}", response_model=OperationResult, tags=["Services"])
def delete_service(service_name: str, ctx: Context):
    """Deletes a managed service."""
    try:
        ctx["config"].delete_service(service_name)
        return OperationResult(success=True, message=f"Service '{service_name}' deleted")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/services/{service_name}/deploy", response_model=OperationResult, tags=["Services"])
def deploy_to_service(service_name: str, ctx: Context):
    """Deploys certificate to a managed service."""
    service = ctx["config"].get_service(service_name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")

    pack_name = service.get("cert_pack_id")
    if not pack_name:
        return OperationResult(success=False, message="No certificate pack assigned to service")

    paths = ctx["cert_store"].get_pack_paths(pack_name)
    if not paths:
        return OperationResult(success=False, message=f"Certificate pack '{pack_name}' not found")

    # Get ClearPass credentials
    cred_id = service.get("credential_id")
    if cred_id:
        cred = ctx["config"].get_clearpass_credential(cred_id)
        if cred:
            service["client_id"] = cred.get("client_id")
            service["client_secret"] = cred.get("client_secret")

    handler = ArubaClearPassHandler(service)
    result = handler.deploy(paths[0], paths[1])

    return OperationResult(
        success=bool(result.get("success")),
        message=result.get("message") or "Deployment failed.",
        data={
            "stage": result.get("stage"),
            "nodes": result.get("nodes", []),
        },
    )


@router.get("/services/{service_name}/health", response_model=OperationResult, tags=["Services"])
def check_service_health(service_name: str, ctx: Context):
    """Checks the health of a managed service."""
    service = ctx["config"].get_service(service_name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")

    # Get ClearPass credentials
    cred_id = service.get("credential_id")
    if cred_id:
        cred = ctx["config"].get_clearpass_credential(cred_id)
        if cred:
            service["client_id"] = cred.get("client_id")
            service["client_secret"] = cred.get("client_secret")

    handler = ArubaClearPassHandler(service)
    result = handler.check_remote_expiry()

    # Update health status in config
    service["health_status"] = result
    ctx["config"].update_service(service_name, {"health_status": result})

    return OperationResult(
        success=result.get("success", False),
        message=result.get("message", "Health check complete"),
        data=result,
    )


# --- ACME Credentials ---


@router.get("/credentials/acme", response_model=list[AcmeCredential], tags=["Credentials"])
def list_acme_credentials(ctx: Context):
    """Lists all ACME credentials (without secrets)."""
    creds = ctx["config"].get_acme_credentials()
    return [
        AcmeCredential(
            id=cred_id,
            name=data.get("name", cred_id),
            provider=data.get("provider", ""),
            email=data.get("email"),
        )
        for cred_id, data in creds.items()
    ]


@router.post("/credentials/acme/test", response_model=OperationResult, tags=["Credentials"])
def test_acme_credential_inline(data: CloudflareTokenTestInput):
    """Tests a Cloudflare token without saving it."""
    return _probe_result(test_cloudflare_token(data.api_token))


@router.post(
    "/credentials/acme/{credential_id}/test",
    response_model=OperationResult,
    tags=["Credentials"],
)
def test_acme_credential(credential_id: str, ctx: Context):
    """Tests a saved ACME credential. Live checks are implemented for Cloudflare."""
    cred = ctx["config"].get_acme_credential(credential_id)
    if not cred:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")
    if cred.get("provider") != "cloudflare":
        provider = cred.get("provider") or "unknown"
        return OperationResult(
            success=False,
            message=(
                "Connection test is available for Cloudflare tokens. "
                f"This credential is {provider}."
            ),
        )
    return _probe_result(test_cloudflare_token(cred.get("api_token") or ""))


@router.post("/credentials/acme", response_model=OperationResult, tags=["Credentials"])
def add_acme_credential(data: AcmeCredentialInput, ctx: Context):
    """Adds a new ACME credential."""
    cred_data = data.model_dump(exclude_none=True)
    cred_data["provider"] = data.provider.value
    cred_id = cred_data.pop("id")
    ctx["config"].set_acme_credential(cred_id, cred_data)
    return OperationResult(success=True, message=f"ACME credential '{cred_id}' saved")


@router.delete(
    "/credentials/acme/{credential_id}",
    response_model=OperationResult,
    tags=["Credentials"],
)
def delete_acme_credential(credential_id: str, ctx: Context):
    """Deletes an ACME credential."""
    if ctx["config"].delete_acme_credential(credential_id):
        return OperationResult(success=True, message=f"ACME credential '{credential_id}' deleted")
    raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")


# --- ClearPass Credentials ---


@router.get(
    "/credentials/clearpass",
    response_model=list[ClearPassCredential],
    tags=["Credentials"],
)
def list_clearpass_credentials(ctx: Context):
    """Lists all ClearPass credentials (without secrets)."""
    creds = ctx["config"].get_clearpass_credentials()
    return [
        ClearPassCredential(
            id=cred_id,
            name=data.get("name", cred_id),
            host=data.get("host", ""),
        )
        for cred_id, data in creds.items()
    ]


@router.post("/credentials/clearpass/test", response_model=OperationResult, tags=["Credentials"])
def test_clearpass_credential_inline(data: ClearPassConnectionTestInput):
    """Tests ClearPass OAuth credentials without saving them."""
    handler = ArubaClearPassHandler(
        {
            "name": "credential-test",
            "host": data.host,
            "client_id": data.client_id,
            "client_secret": data.client_secret,
        }
    )
    return _probe_result(handler.test_connection())


@router.post(
    "/credentials/clearpass/{credential_id}/test",
    response_model=OperationResult,
    tags=["Credentials"],
)
def test_clearpass_credential(credential_id: str, ctx: Context):
    """Tests a saved ClearPass credential by signing in and listing cluster nodes."""
    cred = ctx["config"].get_clearpass_credential(credential_id)
    if not cred:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")
    handler = ArubaClearPassHandler(
        {
            "name": cred.get("name", credential_id),
            "host": cred.get("host", ""),
            "client_id": cred.get("client_id", ""),
            "client_secret": cred.get("client_secret", ""),
        }
    )
    return _probe_result(handler.test_connection())


@router.post("/credentials/clearpass", response_model=OperationResult, tags=["Credentials"])
def add_clearpass_credential(data: ClearPassCredentialInput, ctx: Context):
    """Adds a new ClearPass credential."""
    cred_data = data.model_dump()
    cred_id = cred_data.pop("id")
    ctx["config"].set_clearpass_credential(cred_id, cred_data)
    return OperationResult(success=True, message=f"ClearPass credential '{cred_id}' saved")


@router.delete(
    "/credentials/clearpass/{credential_id}",
    response_model=OperationResult,
    tags=["Credentials"],
)
def delete_clearpass_credential(credential_id: str, ctx: Context):
    """Deletes a ClearPass credential."""
    if ctx["config"].delete_clearpass_credential(credential_id):
        return OperationResult(
            success=True, message=f"ClearPass credential '{credential_id}' deleted"
        )
    raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")


# --- Settings ---


@router.get("/settings", tags=["Settings"])
def get_settings(ctx: Context):
    """Gets application settings."""
    return ctx["config"].get_app_settings()


@router.patch("/settings", response_model=OperationResult, tags=["Settings"])
def update_settings(data: AppSettingsInput, ctx: Context):
    """Updates application settings."""
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    ctx["config"].update_app_settings(update_data)
    return OperationResult(success=True, message="Settings updated")


def _probe_result(result: dict) -> OperationResult:
    """Maps a connection-test dict onto the shared operation response."""
    return OperationResult(
        success=bool(result.get("success")),
        message=result.get("message", ""),
        data=result.get("data"),
    )


# --- ACME Providers ---


@router.get("/providers/acme", tags=["Providers"])
def list_acme_providers():
    """Lists available ACME providers."""
    return [
        {"id": "cloudflare", "name": "Cloudflare", "challenge_type": "dns-01"},
        {"id": "route53", "name": "AWS Route53", "challenge_type": "dns-01"},
        {"id": "digitalocean", "name": "DigitalOcean", "challenge_type": "dns-01"},
        {"id": "google", "name": "Google Cloud DNS", "challenge_type": "dns-01"},
        {"id": "ovh", "name": "OVH", "challenge_type": "dns-01"},
        {"id": "duckdns", "name": "DuckDNS", "challenge_type": "dns-01"},
        {"id": "standalone", "name": "Standalone", "challenge_type": "http-01"},
        {"id": "webroot", "name": "Webroot", "challenge_type": "http-01"},
        {"id": "nginx", "name": "Nginx", "challenge_type": "http-01"},
        {"id": "apache", "name": "Apache", "challenge_type": "http-01"},
    ]
