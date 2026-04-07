# Configuration Reference

Complete reference for configuring Certificate Manager.

---

## Table of Contents

1. [Environment Variables](#environment-variables)
2. [Configuration File (config.yaml)](#configuration-file-configyaml)
3. [Certificate Packs](#certificate-packs)
4. [Services](#services)
5. [Credentials](#credentials)
6. [Settings](#settings)
7. [Directory Structure](#directory-structure)

---

## Environment Variables

Environment variables control application behavior and can be set via `.env` file or directly in the environment.

### Core Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EDGE_DOMAIN` | `localhost` | Primary domain for nginx edge certificates |
| `DATA_DIR` | `/app/data` | Directory for config, certs, and logs |
| `SSL_DIR` | `/etc/letsencrypt` | Certbot letsencrypt directory |
| `LOG_LEVEL` | `INFO` | Logging level |
| `SCHEDULER_ENABLED` | `true` | Enable background scheduler |
| `SCHEDULER_TIME` | `00:30` | Daily renewal check time (UTC) |
| `NGINX_CONTAINER_NAME` | `nginx` | Docker container for nginx reload |

### Log Levels

| Level | Description |
|-------|-------------|
| `DEBUG` | Detailed debugging information |
| `INFO` | General operational information |
| `WARNING` | Warning messages |
| `ERROR` | Error messages only |

### Example .env File

```bash
# Domain Configuration
EDGE_DOMAIN=your-domain.example.com

# Logging
LOG_LEVEL=INFO

# Scheduler
SCHEDULER_ENABLED=true
SCHEDULER_TIME=00:30

# Nginx Integration
NGINX_CONTAINER_NAME=nginx
```

---

## Configuration File (config.yaml)

The main configuration file is stored at `data/config.yaml`. It contains all certificate packs, services, credentials, and settings.

### File Structure

```yaml
# Application settings
settings:
  log_level: INFO
  scheduler_time: "00:30"

# Certificate packs
cert_packs:
  my-domain:
    name: my-domain
    domains:
      - example.com
      - "*.example.com"
    source: acme
    # ... additional fields

# Managed services
services:
  cppm-https:
    name: cppm-https
    host: clearpass.example.com
    # ... additional fields

# ACME credentials (DNS providers)
acme_credentials:
  cloudflare-main:
    id: cloudflare-main
    name: Cloudflare DNS
    # ... additional fields

# ClearPass credentials
clearpass_credentials:
  cppm-prod:
    id: cppm-prod
    name: Production ClearPass
    # ... additional fields
```

### Automatic Backups

Before each configuration change, the application creates a backup in `data/backups/`. The last 20 backups are retained.

```
data/backups/
├── config_20240115_103045.yaml
├── config_20240115_102030.yaml
└── config_20240115_101500.yaml
```

---

## Certificate Packs

Certificate packs contain the certificate files and metadata for a domain or set of domains.

### Schema

```yaml
cert_packs:
  pack-name:
    # Required fields
    name: pack-name              # Unique identifier
    domains:                     # List of domain names
      - example.com
      - "*.example.com"
    source: acme                 # Certificate source

    # ACME-specific fields (source: acme)
    provider: cloudflare         # ACME provider
    challenge_type: dns-01       # Challenge type
    credential_id: cloudflare-main  # ACME credential
    email: admin@example.com     # ACME account email
    auto_renew: true             # Enable auto-renewal

    # Certificate metadata (populated automatically)
    not_before: "2024-01-01T00:00:00+00:00"
    not_after: "2024-04-01T00:00:00+00:00"
    days_remaining: 90
    issuer: "CN=R3,O=Let's Encrypt,C=US"
    subject: "CN=example.com"
    serial_number: "ABC123..."
    key_type: ecc                # Key type (rsa/ecc)

    # Storage location
    is_edge: true                # Edge certificate (nginx)

    # Renewal tracking
    last_renewal: "2024-01-01T00:30:00+00:00"
    last_renewal_status: SUCCESS
```

### Certificate Sources

| Source | Description |
|--------|-------------|
| `acme` | Automatically obtained via Let's Encrypt |
| `manual` | Manually uploaded certificate |

### Key Types

| Type | Description |
|------|-------------|
| `rsa` | RSA 2048-bit key |
| `ecdsa` / `ecc` | ECDSA P-256 key |

### Challenge Types

| Type | Description |
|------|-------------|
| `dns-01` | DNS TXT record challenge |
| `http-01` | HTTP file challenge |

### ACME Providers

| Provider | Challenge | Required Credentials |
|----------|-----------|---------------------|
| `cloudflare` | dns-01 | api_token, email |
| `route53` | dns-01 | access_key_id, secret_access_key |
| `digitalocean` | dns-01 | api_token |
| `google` | dns-01 | service_account_json |
| `ovh` | dns-01 | application_key, application_secret, consumer_key |
| `duckdns` | dns-01 | token |
| `standalone` | http-01 | (none - binds port 80) |
| `webroot` | http-01 | webroot_path |
| `nginx` | http-01 | (none - nginx plugin) |
| `apache` | http-01 | (none - apache plugin) |

---

## Services

Services represent managed endpoints where certificates are deployed.

### Schema

```yaml
services:
  service-name:
    # Required fields
    name: service-name           # Unique identifier
    host: clearpass.example.com  # Service hostname
    credential_id: cppm-prod     # Credential for deployment

    # Optional fields
    type: clearpass              # Service type (default: clearpass)
    cert_pack_id: my-domain      # Associated certificate pack
    cert_usage: "HTTPS(RSA)"     # Certificate usage type
    enabled: true                # Enable monitoring
    additional_nodes: []         # Additional cluster nodes

    # Health status (populated automatically)
    health_status:
      success: true
      expiry: "2024-04-01"
      days_remaining: 90
      subject: "CN=example.com"
      issuer: "CN=R3,O=Let's Encrypt,C=US"

    # Deployment tracking
    last_renewal: null
    last_renewal_status: null
```

### Service Types

| Type | Description |
|------|-------------|
| `clearpass` | HPE Aruba ClearPass Policy Manager |

### Certificate Usage Types

| Usage | Description |
|-------|-------------|
| `HTTPS(RSA)` | HTTPS server (RSA key) |
| `HTTPS(ECC)` | HTTPS server (ECC key) |
| `RADIUS` | RADIUS/EAP server |
| `RadSec` | RADIUS over TLS |
| `Database` | PostgreSQL database |

### Multi-Node Clusters

For ClearPass clusters, specify the publisher as `host` and subscribers in `additional_nodes`:

```yaml
services:
  cppm-cluster:
    name: cppm-cluster
    host: cppm-pub.example.com     # Publisher
    additional_nodes:               # Subscribers
      - cppm-sub1.example.com
      - cppm-sub2.example.com
```

---

## Credentials

### ACME Credentials

ACME credentials are used for DNS-01 challenges with Let's Encrypt.

#### Cloudflare

```yaml
acme_credentials:
  cloudflare-main:
    id: cloudflare-main
    name: Cloudflare DNS
    provider: cloudflare
    api_token: "your-cloudflare-api-token"
    email: admin@example.com
```

**Cloudflare API Token Requirements**:
- Zone:Zone:Read
- Zone:DNS:Edit

#### AWS Route53

```yaml
acme_credentials:
  route53-aws:
    id: route53-aws
    name: AWS Route53
    provider: route53
    access_key_id: "AKIAIOSFODNN7EXAMPLE"
    secret_access_key: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    region: us-east-1
```

**IAM Policy Requirements**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:GetChange",
        "route53:ChangeResourceRecordSets"
      ],
      "Resource": "*"
    }
  ]
}
```

#### DigitalOcean

```yaml
acme_credentials:
  do-dns:
    id: do-dns
    name: DigitalOcean DNS
    provider: digitalocean
    api_token: "dop_v1_your-token"
```

#### Google Cloud DNS

```yaml
acme_credentials:
  google-dns:
    id: google-dns
    name: Google Cloud DNS
    provider: google
    service_account_json: |
      {
        "type": "service_account",
        "project_id": "your-project",
        ...
      }
```

#### OVH

```yaml
acme_credentials:
  ovh-dns:
    id: ovh-dns
    name: OVH DNS
    provider: ovh
    endpoint: ovh-eu
    application_key: "your-app-key"
    application_secret: "your-app-secret"
    consumer_key: "your-consumer-key"
```

#### DuckDNS

```yaml
acme_credentials:
  duckdns:
    id: duckdns
    name: DuckDNS
    provider: duckdns
    token: "your-duckdns-token"
```

### ClearPass Credentials

```yaml
clearpass_credentials:
  cppm-prod:
    id: cppm-prod
    name: Production ClearPass
    host: clearpass.example.com
    client_id: "cert-manager"
    client_secret: "your-oauth-client-secret"
    verify_ssl: false
```

**Fields**:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier |
| `name` | Yes | Display name |
| `host` | Yes | ClearPass hostname |
| `client_id` | Yes | OAuth2 client ID |
| `client_secret` | Yes | OAuth2 client secret |
| `verify_ssl` | No | Verify SSL certificate (default: false) |

---

## Settings

Application-wide settings.

### Schema

```yaml
settings:
  log_level: INFO
  scheduler_time: "00:30"
```

### Available Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `log_level` | `INFO` | Logging level |
| `scheduler_time` | `00:30` | Daily renewal check time (HH:MM UTC) |

### Via API

```bash
# Get settings
curl http://localhost:8000/api/settings

# Update settings
curl -X PATCH http://localhost:8000/api/settings \
  -H "Content-Type: application/json" \
  -d '{"log_level": "DEBUG", "scheduler_time": "02:00"}'
```

---

## Directory Structure

### Application Directory Layout

```
cert-manager/
├── src/
│   └── cert_manager/          # Application source code
│       ├── api/               # REST API
│       ├── core/              # Core modules
│       ├── acme/              # ACME/Certbot
│       ├── handlers/          # Service handlers
│       └── services/          # Background services
├── data/                      # Persistent data
│   ├── config.yaml            # Main configuration
│   ├── certs/                 # Non-edge certificates
│   ├── logs/                  # Application logs
│   └── backups/               # Config backups
├── ssl/                       # Certbot directory
│   ├── live/                  # Current certificates
│   ├── archive/               # Certificate history
│   ├── renewal/               # Renewal configs
│   ├── accounts/              # ACME accounts
│   └── logs/                  # Certbot logs
├── docs/                      # Documentation
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env                       # Environment config
└── README.md
```

### Certificate Storage

#### Edge Certificates (is_edge: true)

Edge certificates are stored in the ssl directory for nginx:

```
ssl/live/
└── example.com/
    ├── fullchain.pem          # Certificate + chain
    ├── privkey.pem            # Private key
    ├── cert.pem               # Certificate only
    └── chain.pem              # CA chain only
```

#### Non-Edge Certificates (is_edge: false)

Non-edge certificates are stored in the data directory:

```
data/certs/
└── my-pack/
    ├── fullchain.pem
    └── privkey.pem
```

### Log Files

```
data/logs/
└── cert-manager.log           # Main application log

ssl/logs/
└── letsencrypt.log            # Certbot logs
```

### Configuration Backups

```
data/backups/
├── config_20240115_103045.yaml
├── config_20240115_102030.yaml
└── config_20240115_101500.yaml
```

Backups are named with timestamp: `config_YYYYMMDD_HHMMSS.yaml`

---

## Example Complete Configuration

```yaml
settings:
  log_level: INFO
  scheduler_time: "00:30"

cert_packs:
  example-wildcard:
    name: example-wildcard
    domains:
      - example.com
      - "*.example.com"
    source: acme
    provider: cloudflare
    challenge_type: dns-01
    credential_id: cloudflare-main
    email: admin@example.com
    key_type: ecdsa
    auto_renew: true
    is_edge: true
    not_before: "2024-01-01T00:00:00+00:00"
    not_after: "2024-04-01T00:00:00+00:00"
    days_remaining: 90
    issuer: "CN=R3,O=Let's Encrypt,C=US"
    subject: "CN=example.com"
    serial_number: "03ABC..."
    last_renewal: "2024-01-01T00:30:00+00:00"
    last_renewal_status: SUCCESS

  clearpass-cert:
    name: clearpass-cert
    domains:
      - clearpass.example.com
    source: acme
    provider: cloudflare
    challenge_type: dns-01
    credential_id: cloudflare-main
    email: admin@example.com
    key_type: rsa
    auto_renew: true
    is_edge: false
    not_before: "2024-01-01T00:00:00+00:00"
    not_after: "2024-04-01T00:00:00+00:00"
    days_remaining: 90
    issuer: "CN=R3,O=Let's Encrypt,C=US"
    subject: "CN=clearpass.example.com"
    serial_number: "04DEF..."
    last_renewal: "2024-01-01T00:30:00+00:00"
    last_renewal_status: SUCCESS

services:
  cppm-https:
    name: cppm-https
    host: clearpass.example.com
    type: clearpass
    cert_pack_id: clearpass-cert
    cert_usage: "HTTPS(RSA)"
    credential_id: cppm-prod
    enabled: true
    additional_nodes: []
    health_status:
      success: true
      expiry: "2024-04-01"
      days_remaining: 90
      subject: "CN=clearpass.example.com"
      issuer: "CN=R3,O=Let's Encrypt,C=US"
    last_renewal: "2024-01-01T00:35:00+00:00"
    last_renewal_status: SUCCESS

acme_credentials:
  cloudflare-main:
    id: cloudflare-main
    name: Cloudflare DNS
    provider: cloudflare
    api_token: "cf-api-token-here"
    email: admin@example.com

clearpass_credentials:
  cppm-prod:
    id: cppm-prod
    name: Production ClearPass
    host: clearpass.example.com
    client_id: cert-manager
    client_secret: "oauth-client-secret-here"
    verify_ssl: false
```
