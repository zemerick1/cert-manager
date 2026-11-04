"""Pydantic models for API request/response schemas."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CertSource(str, Enum):
    ACME = "acme"
    MANUAL = "manual"


class KeyType(str, Enum):
    RSA = "rsa"
    ECDSA = "ecdsa"


class ChallengeType(str, Enum):
    DNS_01 = "dns-01"
    HTTP_01 = "http-01"
    TLS_ALPN_01 = "tls-alpn-01"


class AcmeProvider(str, Enum):
    CLOUDFLARE = "cloudflare"
    ROUTE53 = "route53"
    DIGITALOCEAN = "digitalocean"
    GOOGLE = "google"
    OVH = "ovh"
    DUCKDNS = "duckdns"
    STANDALONE = "standalone"
    WEBROOT = "webroot"
    NGINX = "nginx"
    APACHE = "apache"


class RenewalStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"
    NEVER = "NEVER"
    MAX_RETRIES = "MAX_RETRIES"


class ServiceType(str, Enum):
    CLEARPASS = "clearpass"


class CertUsage(str, Enum):
    HTTPS_RSA = "HTTPS(RSA)"
    HTTPS_ECC = "HTTPS(ECC)"
    RADIUS = "RADIUS"
    RADSEC = "RadSec"
    DATABASE = "Database"


# --- Response Models ---


class HealthResponse(BaseModel):
    status: str
    scheduler_running: bool
    total_cert_packs: int
    total_services: int
    certs_expiring_soon: int
    next_renewal_check: Optional[str] = None
    callback_base: str = ""


class CertPack(BaseModel):
    name: str
    domains: list[str] = []
    source: str
    not_before: Optional[str] = None
    not_after: Optional[str] = None
    days_remaining: Optional[int] = None
    issuer: Optional[str] = None
    subject: Optional[str] = None
    serial_number: Optional[str] = None
    key_type: Optional[str] = None
    auto_renew: bool = False
    is_edge: bool = False
    provider: Optional[str] = None
    challenge_type: Optional[str] = None
    credential_id: Optional[str] = None
    last_renewal: Optional[str] = None
    last_renewal_status: str = "NEVER"


class ManagedService(BaseModel):
    name: str
    host: str
    type: str
    cert_pack_id: Optional[str] = None
    cert_usage: str = "HTTPS(RSA)"
    enabled: bool = True
    credential_id: Optional[str] = None
    additional_nodes: list[str] = []
    health_status: Optional[dict] = None
    last_renewal: Optional[dict] = None


class AcmeCredential(BaseModel):
    id: str
    name: str
    provider: str
    email: Optional[str] = None


class ClearPassCredential(BaseModel):
    id: str
    name: str
    host: str
    additional_nodes: list[str] = []


class OperationResult(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None


# --- Request Models ---


class CertRequestInput(BaseModel):
    pack_name: str = Field(..., description="Name for the certificate pack")
    domains: list[str] = Field(..., description="List of domain names")
    provider: AcmeProvider = Field(..., description="ACME provider")
    credential_id: str = Field(..., description="Credential ID")
    email: str = Field(..., description="ACME account email")
    challenge_type: ChallengeType = ChallengeType.DNS_01
    key_type: KeyType = KeyType.ECDSA
    is_edge: bool = Field(False, description="Save as edge certificate for nginx")


class CertUploadInput(BaseModel):
    pack_name: str = Field(..., description="Name for the certificate pack")
    fullchain: str = Field(..., description="PEM-encoded certificate chain")
    privkey: str = Field(..., description="PEM-encoded private key")
    is_edge: bool = False


class ServiceInput(BaseModel):
    name: str = Field(..., description="Service name")
    host: str = Field(..., description="Service host")
    type: ServiceType = ServiceType.CLEARPASS
    cert_pack_id: Optional[str] = None
    cert_usage: CertUsage = CertUsage.HTTPS_RSA
    enabled: bool = True
    credential_id: Optional[str] = None
    additional_nodes: list[str] = []


class ServiceUpdateInput(BaseModel):
    host: Optional[str] = None
    cert_pack_id: Optional[str] = None
    cert_usage: Optional[CertUsage] = None
    enabled: Optional[bool] = None
    credential_id: Optional[str] = None
    additional_nodes: Optional[list[str]] = None


class AcmeCredentialInput(BaseModel):
    id: str = Field(..., description="Unique credential ID")
    name: str = Field(..., description="Display name")
    provider: AcmeProvider = Field(..., description="ACME provider type")
    api_token: Optional[str] = Field(None, description="API token (Cloudflare, DigitalOcean)")
    email: Optional[str] = Field(None, description="Account email")
    access_key_id: Optional[str] = Field(None, description="AWS Access Key ID (Route53)")
    secret_access_key: Optional[str] = Field(None, description="AWS Secret Access Key (Route53)")
    region: Optional[str] = Field(None, description="AWS Region (Route53)")


class ClearPassCredentialInput(BaseModel):
    id: str = Field(..., description="Unique credential ID")
    name: str = Field(..., description="Display name")
    host: str = Field(..., description="ClearPass publisher hostname")
    client_id: str = Field(..., description="OAuth client ID")
    client_secret: str = Field(..., description="OAuth client secret")
    verify_ssl: bool = False
    additional_nodes: list[str] = Field(
        default_factory=list,
        description="Subscriber hostnames contacted in addition to the publisher",
    )


class AppSettingsInput(BaseModel):
    log_level: Optional[str] = None
    scheduler_time: Optional[str] = None


class CertJob(BaseModel):
    job_id: str
    pack_name: str
    kind: str
    status: str
    progress: list[str] = []
    success: Optional[bool] = None
    message: Optional[str] = None


class CloudflareTokenTestInput(BaseModel):
    api_token: str = Field(..., min_length=1, description="Cloudflare API token to test")


class ClearPassConnectionTestInput(BaseModel):
    host: str = Field(..., min_length=1, description="ClearPass publisher hostname")
    client_id: str = Field(..., min_length=1, description="OAuth client ID")
    client_secret: str = Field(..., min_length=1, description="OAuth client secret")
