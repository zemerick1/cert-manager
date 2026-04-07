# Architecture Overview

**Version**: 1.0.0
**Last Updated**: 2024

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Component Overview](#3-component-overview)
4. [Data Flow](#4-data-flow)
5. [Technology Stack](#5-technology-stack)
6. [Directory Structure](#6-directory-structure)

---

## 1. Executive Summary

Certificate Manager is a standalone application for automated certificate lifecycle management. It provides:

- **ACME Certificate Management**: Automated Let's Encrypt certificate issuance and renewal via Certbot
- **ClearPass Deployment**: Certificate deployment to Aruba ClearPass clusters via REST API
- **Background Scheduling**: Automatic renewal and health monitoring
- **REST API**: Simple FastAPI-based interface with interactive documentation

The application is designed to run as a single Docker container with minimal external dependencies.

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
                    +------------------+
                    |   REST Clients   |
                    |  (curl, browser) |
                    +--------+---------+
                             |
                             | HTTP/HTTPS
                             |
                    +--------v---------+
                    |     FastAPI      |
                    |   REST API       |
                    |   Port 8000      |
                    +--------+---------+
                             |
         +-------------------+-------------------+
         |                   |                   |
+--------v-------+  +--------v-------+  +--------v-------+
|  ACME Manager  |  | Config Manager |  |   Scheduler    |
|  (Certbot)     |  | (YAML + Creds) |  | (Background)   |
+--------+-------+  +--------+-------+  +--------+-------+
         |                   |                   |
         |                   |                   |
+--------v-------+  +--------v-------+  +--------v-------+
|  Cert Store    |  |  Credentials   |  | Health Checks  |
| (Filesystem)   |  | (Built-in)     |  | (TLS/API)      |
+--------+-------+  +----------------+  +--------+-------+
         |                                       |
         |                                       |
+--------v-------+                      +--------v-------+
|  SSL Directory |                      |   ClearPass    |
| /etc/letsencrypt|                     |   REST API     |
+----------------+                      +----------------+
```

### 2.2 Container Architecture

```
+--------------------------------------------------+
|              Docker Container                     |
|  +--------------------------------------------+  |
|  |           cert-manager (Python 3.12)       |  |
|  |                                            |  |
|  |  +----------+  +----------+  +----------+  |  |
|  |  | FastAPI  |  | Certbot  |  | Scheduler|  |  |
|  |  | REST API |  | ACME     |  | (asyncio)|  |  |
|  |  +----------+  +----------+  +----------+  |  |
|  +--------------------------------------------+  |
|                                                  |
|  Volumes:                                        |
|  - /app/data      (config, certs, logs)         |
|  - /etc/letsencrypt (edge certs)                |
|  - /var/run/docker.sock (nginx reload)          |
+--------------------------------------------------+
```

---

## 3. Component Overview

### 3.1 API Layer (`api/`)

| Component | File | Purpose |
|-----------|------|---------|
| Models | `models.py` | Pydantic request/response schemas |
| Routes | `routes.py` | FastAPI endpoint handlers |

**Key Features**:
- RESTful API design
- Automatic OpenAPI documentation
- Request validation via Pydantic
- Dependency injection for app context

### 3.2 Core Layer (`core/`)

| Component | File | Purpose |
|-----------|------|---------|
| Config Manager | `config_manager.py` | YAML config with built-in credentials |
| Cert Store | `cert_store.py` | Certificate file management |
| Cert Validator | `cert_validator.py` | X.509 parsing and validation |
| Crypto Utils | `crypto_utils.py` | Fernet encryption utilities |

**Key Features**:
- Dual-location certificate storage (edge vs non-edge)
- Automatic config backup rotation (keeps 20 versions)
- Built-in credential management (no external dependencies)

### 3.3 ACME Layer (`acme/`)

| Component | File | Purpose |
|-----------|------|---------|
| ACME Manager | `manager.py` | Certbot CLI wrapper |

**Supported Providers**:
- DNS-01: Cloudflare, Route53, DigitalOcean, Google, OVH, DuckDNS
- HTTP-01: Standalone, Webroot, Nginx, Apache

**Key Features**:
- Automatic retry on lock file conflicts
- Progress streaming during certificate requests
- Retry tracking with max attempts (5)

### 3.4 Handlers Layer (`handlers/`)

| Component | File | Purpose |
|-----------|------|---------|
| Base Handler | `base.py` | Abstract certificate handler |
| ClearPass Handler | `clearpass.py` | ClearPass deployment |
| CA Trust | `clearpass_ca_trust.py` | CA chain management |

**Key Features**:
- OAuth2 authentication
- Multi-node cluster support
- Automatic CA trust list management
- PFX generation for ClearPass

### 3.5 Services Layer (`services/`)

| Component | File | Purpose |
|-----------|------|---------|
| Scheduler | `scheduler.py` | Background renewal and monitoring |
| Nginx Reload | `nginx_reload.py` | Docker socket SIGHUP |

**Key Features**:
- Daily renewal checks at configurable time
- Service health monitoring every 5 minutes
- Automatic re-deployment on certificate mismatch

---

## 4. Data Flow

### 4.1 Certificate Request Flow

```
User Request
     |
     v
POST /api/certs/request
     |
     v
Validate Input (Pydantic)
     |
     v
Load Credentials (ConfigManager)
     |
     v
Save Pending Metadata
     |
     v
Run Certbot (subprocess)
     |
     +---> DNS Provider API (if dns-01)
     |
     v
Import Certificate (CertStore)
     |
     +---> /etc/letsencrypt/live/{name}/ (if edge)
     |---> /app/data/certs/{name}/ (if non-edge)
     |
     v
Update Metadata (SUCCESS)
     |
     v
Reload Nginx (if edge)
     |
     v
Return Response
```

### 4.2 ClearPass Deployment Flow

```
POST /api/services/{name}/deploy
     |
     v
Load Service Config
     |
     v
Load ClearPass Credentials
     |
     v
Get Certificate Paths
     |
     v
Generate PFX (openssl)
     |
     v
Authenticate (OAuth2)
     |
     v
Ensure CA Trust
     |
     +---> Extract CA chain
     +---> Resolve AIA parents
     +---> Upload missing CAs
     |
     v
Get Cluster Servers
     |
     v
For each server:
     |
     +---> Register PFX download
     +---> PUT /api/server-cert/name/{uuid}/{usage}
     +---> ClearPass fetches PFX via callback URL
     |
     v
Return Result
```

### 4.3 Background Scheduler Flow

```
+------------------+     +--------------------+
|  Renewal Loop    |     |  Monitor Loop      |
|  (Daily)         |     |  (Every 5 min)     |
+--------+---------+     +----------+---------+
         |                          |
         v                          v
Wait until scheduler_time    Check all services
         |                          |
         v                          v
Get renewable packs          Health check (TLS/API)
         |                          |
         v                          v
Renew each pack              Detect cert mismatch?
         |                          |
         v                          +---> Auto-deploy
Reload nginx (if edge)              |
         |                          v
         v                   Retry pending certs
Auto-deploy to services             |
         |                          v
         v                   Sleep 5 minutes
Sleep until next day                |
         |                          |
         +--------<-----------------+
```

---

## 5. Technology Stack

### 5.1 Runtime

| Component | Technology | Version |
|-----------|------------|---------|
| Language | Python | 3.11+ |
| Web Framework | FastAPI | 0.110+ |
| ASGI Server | Uvicorn | 0.27+ |
| ACME Client | Certbot | 2.9+ |

### 5.2 Core Libraries

| Library | Purpose |
|---------|---------|
| `cryptography` | X.509 parsing, Fernet encryption |
| `pyyaml` | YAML configuration |
| `pydantic` | Data validation |
| `pydantic-settings` | Environment configuration |
| `requests` | HTTP client (ClearPass API) |
| `requests-unixsocket` | Docker socket communication |

### 5.3 Certbot DNS Plugins

| Plugin | Provider |
|--------|----------|
| `certbot-dns-cloudflare` | Cloudflare |
| `certbot-dns-route53` | AWS Route53 |
| `certbot-dns-digitalocean` | DigitalOcean |

---

## 6. Directory Structure

### 6.1 Application Structure

```
cert-manager/
├── src/cert_manager/
│   ├── __init__.py
│   ├── app.py                 # FastAPI application
│   ├── config.py              # Pydantic settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── models.py          # Request/response schemas
│   │   └── routes.py          # API endpoints
│   ├── acme/
│   │   ├── __init__.py
│   │   └── manager.py         # Certbot wrapper
│   ├── core/
│   │   ├── __init__.py
│   │   ├── cert_store.py      # Certificate storage
│   │   ├── cert_validator.py  # X.509 utilities
│   │   ├── config_manager.py  # YAML config
│   │   └── crypto_utils.py    # Encryption
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── base.py            # Abstract handler
│   │   ├── clearpass.py       # ClearPass deployment
│   │   └── clearpass_ca_trust.py
│   └── services/
│       ├── __init__.py
│       ├── nginx_reload.py    # Docker SIGHUP
│       └── scheduler.py       # Background tasks
├── docs/                      # Documentation
├── data/                      # Runtime data
│   ├── config.yaml           # Configuration
│   ├── certs/                # Non-edge certificates
│   ├── logs/                 # Application logs
│   └── backups/              # Config backups
└── ssl/                      # Edge certificates
    └── live/
        └── {domain}/
            ├── fullchain.pem
            └── privkey.pem
```

### 6.2 Data Directory Structure

```
data/
├── config.yaml              # Main configuration
├── certs/                   # Non-edge certificate packs
│   ├── {pack-name}/
│   │   ├── fullchain.pem
│   │   └── privkey.pem
│   └── ...
├── logs/
│   └── cert-manager.log     # Rotating log (5MB, 3 backups)
└── backups/
    └── config/
        └── config.{timestamp}.yaml.bak  # Auto-rotated (keep 20)
```

### 6.3 SSL Directory Structure

```
ssl/
├── live/                    # Active certificates
│   ├── {domain}/           # Pack directory
│   │   ├── fullchain.pem
│   │   └── privkey.pem
│   └── {edge-domain} -> {pack-name}  # Symlink if different
├── archive/                 # Certbot archives
├── renewal/                 # Certbot renewal configs
├── work/                    # Certbot work directory
└── logs/                    # Certbot logs
```

---

**Document Maintainer**: Infrastructure Team
**Review Cycle**: As needed
