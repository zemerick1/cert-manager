# ClearPass Integration Guide

This guide covers integrating Certificate Manager with HPE Aruba ClearPass Policy Manager for automated certificate deployment.

---

## Table of Contents

1. [Overview](#overview)
2. [ClearPass Prerequisites](#clearpass-prerequisites)
3. [OAuth2 API Client Setup](#oauth2-api-client-setup)
4. [Adding ClearPass Credentials](#adding-clearpass-credentials)
5. [Certificate Usage Types](#certificate-usage-types)
6. [Service Configuration](#service-configuration)
7. [Multi-Node Clusters](#multi-node-clusters)
8. [CA Trust List Management](#ca-trust-list-management)
9. [Deployment Process](#deployment-process)
10. [Troubleshooting](#troubleshooting)

---

## Overview

Certificate Manager integrates with ClearPass via the REST API to:

1. **Deploy Certificates**: Upload and install server certificates
2. **Manage CA Trust**: Automatically upload CA certificates to trust lists
3. **Health Monitoring**: Check deployed certificate status
4. **Auto-Deployment**: Detect mismatches and re-deploy on renewal

### Supported Certificate Types

| Usage | Purpose |
|-------|---------|
| HTTPS(RSA) | Web UI/API server certificate (RSA key) |
| HTTPS(ECC) | Web UI/API server certificate (ECC key) |
| RADIUS | RADIUS/EAP authentication server |
| RadSec | RADIUS over TLS |
| Database | PostgreSQL database server |

---

## ClearPass Prerequisites

### Minimum Version

- ClearPass Policy Manager 6.9.0 or later
- REST API enabled (Administration > Server Manager > Server Configuration)

### Required Permissions

The API client needs access to:

- **Certificate Management**: Upload, install, delete certificates
- **Trust List Management**: Create and modify CA trust lists
- **Server Configuration**: View server certificate status

### Network Access

Ensure the Certificate Manager can reach:

| Destination | Port | Protocol |
|-------------|------|----------|
| ClearPass Publisher | 443 | HTTPS |
| ClearPass Subscribers | 443 | HTTPS (if additional_nodes configured) |

---

## OAuth2 API Client Setup

### Step 1: Create API Client in ClearPass

1. Log in to ClearPass Policy Manager
2. Navigate to **Administration > API Services > API Clients**
3. Click **Add**

### Step 2: Configure Client Settings

| Field | Value |
|-------|-------|
| Client ID | `cert-manager` (or your choice) |
| Description | Certificate Manager Integration |
| Enabled | Yes |
| Operating Mode | ClearPass REST API |
| Operator Profile | Super Administrator |
| Grant Type | Client Credentials |
| Access Token Lifetime | 28800 (8 hours) |

### Step 3: Generate Client Secret

1. After creating the client, click **Generate New Secret**
2. Copy the Client Secret immediately (it won't be shown again)
3. Store securely - you'll need this for credential configuration

### Step 4: Verify API Access

Test the API client:

```bash
# Get access token
curl -X POST "https://clearpass.example.com/api/oauth" \
  -H "Content-Type: application/json" \
  -d '{
    "grant_type": "client_credentials",
    "client_id": "cert-manager",
    "client_secret": "your-client-secret"
  }'

# Expected response
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9...",
  "token_type": "Bearer",
  "expires_in": 28800
}
```

---

## Adding ClearPass Credentials

### Via API

```bash
curl -X POST http://localhost:8000/api/credentials/clearpass \
  -H "Content-Type: application/json" \
  -d '{
    "id": "cppm-prod",
    "name": "Production ClearPass",
    "host": "clearpass.example.com",
    "client_id": "cert-manager",
    "client_secret": "your-oauth-client-secret",
    "verify_ssl": false
  }'
```

### Credential Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier for this credential |
| `name` | Yes | Display name |
| `host` | Yes | ClearPass publisher hostname (FQDN) |
| `client_id` | Yes | OAuth2 client ID |
| `client_secret` | Yes | OAuth2 client secret |
| `verify_ssl` | No | Verify SSL certificate (default: false) |

### SSL Verification

ClearPass often uses self-signed certificates. Set `verify_ssl: false` unless you have:

- A CA-signed certificate on ClearPass
- The CA certificate in the system trust store

---

## Certificate Usage Types

### HTTPS (RSA/ECC)

For the ClearPass web interface and REST API.

```json
{
  "cert_usage": "HTTPS(RSA)"
}
```

**Requirements**:
- Certificate CN/SAN must match the ClearPass FQDN
- RSA key for HTTPS(RSA), ECC key for HTTPS(ECC)

### RADIUS / EAP

For 802.1X authentication (PEAP, EAP-TLS, etc.).

```json
{
  "cert_usage": "RADIUS"
}
```

**Requirements**:
- Certificate should be trusted by supplicants
- Consider using a well-known CA for easier client trust

### RadSec

For RADIUS over TLS to proxy servers or NAS devices.

```json
{
  "cert_usage": "RadSec"
}
```

**Requirements**:
- Certificate CN/SAN should match RADIUS server identity
- Both client and server certificates may be needed

### Database

For PostgreSQL database encryption.

```json
{
  "cert_usage": "Database"
}
```

**Note**: Database certificates are typically self-signed. Manual deployment may be required for initial setup.

---

## Service Configuration

### Add a ClearPass Service

```bash
curl -X POST http://localhost:8000/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "cppm-https",
    "host": "clearpass.example.com",
    "type": "clearpass",
    "cert_pack_id": "my-domain",
    "cert_usage": "HTTPS(RSA)",
    "credential_id": "cppm-prod",
    "enabled": true
  }'
```

### Service Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | - | Unique service identifier |
| `host` | Yes | - | ClearPass publisher hostname |
| `type` | No | `clearpass` | Service type |
| `cert_pack_id` | No | - | Associated certificate pack |
| `cert_usage` | No | `HTTPS(RSA)` | Certificate usage type |
| `credential_id` | Yes | - | ClearPass credential ID |
| `enabled` | No | `true` | Enable monitoring/auto-deploy |
| `additional_nodes` | No | `[]` | Additional cluster nodes |

### Deploy Certificate

```bash
curl -X POST http://localhost:8000/api/services/cppm-https/deploy
```

### Check Service Health

```bash
curl http://localhost:8000/api/services/cppm-https/health
```

Response:

```json
{
  "success": true,
  "message": "Health check complete",
  "data": {
    "success": true,
    "expiry": "2024-04-01",
    "days_remaining": 75,
    "subject": "CN=clearpass.example.com",
    "issuer": "CN=R3,O=Let's Encrypt,C=US",
    "serial_number": "ABC123..."
  }
}
```

---

## Multi-Node Clusters

### Overview

ClearPass clusters consist of:

- **Publisher**: Primary node, handles API requests
- **Subscribers**: Secondary nodes, replicate from publisher

Certificate deployment happens on the **Publisher only**. ClearPass automatically replicates to subscribers.

### Configuration

Specify additional nodes for health monitoring:

```bash
curl -X POST http://localhost:8000/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "cppm-cluster",
    "host": "cppm-pub.example.com",
    "type": "clearpass",
    "cert_pack_id": "my-domain",
    "cert_usage": "HTTPS(RSA)",
    "credential_id": "cppm-prod",
    "additional_nodes": [
      "cppm-sub1.example.com",
      "cppm-sub2.example.com"
    ]
  }'
```

### How It Works

1. **Deployment**: Certificates are uploaded to the Publisher only
2. **Replication**: ClearPass handles replication to Subscribers
3. **Health Check**: Certificate Manager checks all nodes
4. **Mismatch Detection**: If any node has wrong cert, re-deploy is triggered

### Best Practices

- Always use the Publisher hostname as the primary `host`
- Include all Subscribers in `additional_nodes`
- Allow 5-10 minutes for replication after deployment
- Health checks verify serial numbers match across nodes

---

## CA Trust List Management

### Automatic CA Upload

When deploying a certificate, Certificate Manager automatically:

1. **Extracts CA Certificates**: Parses the certificate chain
2. **Fetches Missing CAs**: Uses AIA (Authority Information Access) extension
3. **Uploads to Trust List**: Creates/updates CAs in ClearPass
4. **Updates Usage Types**: Enables CAs for required purposes

### Trust List Usage Types

| Usage | Description |
|-------|-------------|
| AD/LDAP | Active Directory/LDAP server trust |
| EAP | 802.1X EAP authentication |
| HTTPS(Apache) | Web server trust |
| Database | Database server trust |
| RadSec | RADIUS over TLS |
| Endpoint Context Server | External context servers |
| Others | General purpose |

### Manual Trust List Management

Currently, CA trust list is managed automatically during certificate deployment. If you need manual control:

1. Use ClearPass UI: **Administration > Certificates > Trust List**
2. Or use the ClearPass REST API directly

### CA Certificate Requirements

- **Format**: PEM (Base64 encoded)
- **Type**: CA certificates only (Basic Constraints: CA:TRUE)
- **Chain**: Intermediate and root CAs

---

## Deployment Process

### Step-by-Step Flow

```
1. Certificate Manager receives deploy request
                    │
                    ▼
2. Load certificate pack (fullchain.pem, privkey.pem)
                    │
                    ▼
3. Authenticate to ClearPass (OAuth2)
                    │
                    ▼
4. Extract CA certificates from chain
                    │
                    ▼
5. Fetch missing CAs via AIA
                    │
                    ▼
6. Upload CA certificates to trust list
                    │
                    ▼
7. Generate PFX (PKCS#12) from cert/key
                    │
                    ▼
8. Upload PFX to ClearPass
                    │
                    ▼
9. Install certificate for usage type
                    │
                    ▼
10. Wait for replication (clusters)
                    │
                    ▼
11. Verify deployment via health check
```

### PFX Generation

Certificates are converted to PKCS#12 format with:

- **Encryption**: AES-256-CBC
- **MAC**: SHA-256
- **Password**: Random 32-character password (per deployment)

### API Calls Made

| Action | ClearPass API Endpoint |
|--------|----------------------|
| Get Token | `POST /api/oauth` |
| List Trust | `GET /api/server-cert/trust-list` |
| Add CA | `POST /api/server-cert/trust-list` |
| Update CA | `PATCH /api/server-cert/trust-list/{id}` |
| Upload PFX | `POST /api/server-cert/import/server` |
| Install Cert | `POST /api/server-cert/{id}/install` |
| Get Cert | `GET /api/server-cert/details/{usage}` |

---

## Troubleshooting

### Common Issues

#### 1. Authentication Failed

**Symptoms**: `401 Unauthorized` or `invalid_client` error

**Solutions**:
- Verify client_id and client_secret
- Check API client is enabled in ClearPass
- Ensure grant type is "Client Credentials"
- Verify network connectivity to ClearPass

```bash
# Test authentication
curl -X POST "https://clearpass.example.com/api/oauth" \
  -H "Content-Type: application/json" \
  -d '{"grant_type":"client_credentials","client_id":"cert-manager","client_secret":"xxx"}'
```

#### 2. Certificate Upload Failed

**Symptoms**: Deployment fails during PFX upload

**Solutions**:
- Ensure certificate chain is complete
- Verify private key matches certificate
- Check certificate is not expired
- Verify API client has certificate permissions

#### 3. Installation Failed

**Symptoms**: Certificate uploads but doesn't install

**Solutions**:
- Check certificate usage type is correct
- Verify certificate key type matches usage (RSA vs ECC)
- Ensure no other certificate is locked for this usage
- Check ClearPass cluster services are healthy

#### 4. Replication Timeout

**Symptoms**: Publisher has cert but subscribers don't

**Solutions**:
- Check ClearPass replication status (Administration > Server Manager)
- Verify network connectivity between nodes
- Increase health check interval for large clusters
- Manual trigger replication if needed

#### 5. SSL Verification Errors

**Symptoms**: `SSL: CERTIFICATE_VERIFY_FAILED`

**Solutions**:
- Set `verify_ssl: false` in credentials (common for self-signed)
- Or add ClearPass CA to system trust store

### Debug Logging

Enable debug logging for detailed information:

```bash
LOG_LEVEL=DEBUG docker compose up
```

Look for:
- OAuth token requests/responses
- API call details
- Certificate parsing information
- PFX generation steps

### API Exploration

Use ClearPass API documentation to troubleshoot:

```
https://clearpass.example.com/api-docs/
```

### Health Check Details

```bash
curl http://localhost:8000/api/services/cppm-https/health
```

Examine response for:
- `success`: Overall health status
- `serial_number`: Deployed certificate serial
- `expiry`: Certificate expiration date
- `subject`/`issuer`: Certificate details

### Log Files

```bash
# Application logs
cat data/logs/cert-manager.log | grep -i clearpass

# Docker logs
docker compose logs cert-manager 2>&1 | grep -i clearpass
```

---

## Security Recommendations

### Credential Protection

1. **Restrict file permissions**: `chmod 600 data/config.yaml`
2. **Use dedicated API client**: Don't share with other integrations
3. **Minimal permissions**: Only grant required API access
4. **Rotate secrets**: Periodically regenerate client secrets

### Network Security

1. **Use private networks**: Don't expose ClearPass API publicly
2. **Firewall rules**: Limit source IPs for API access
3. **TLS everywhere**: Ensure all connections use HTTPS

### Audit Trail

ClearPass logs all API actions. Review:

- **Administration > Monitoring > Audit Viewer**
- Filter by API client ID

---

## Example: Complete Setup

### 1. Create Credential

```bash
curl -X POST http://localhost:8000/api/credentials/clearpass \
  -H "Content-Type: application/json" \
  -d '{
    "id": "cppm-prod",
    "name": "Production ClearPass Cluster",
    "host": "cppm-pub.example.com",
    "client_id": "cert-manager",
    "client_secret": "your-secret-here",
    "verify_ssl": false
  }'
```

### 2. Request Certificate

```bash
curl -X POST http://localhost:8000/api/certs/request \
  -H "Content-Type: application/json" \
  -d '{
    "pack_name": "clearpass-cert",
    "domains": ["cppm-pub.example.com", "cppm-sub1.example.com", "cppm-sub2.example.com"],
    "provider": "cloudflare",
    "credential_id": "cloudflare-main",
    "email": "admin@example.com",
    "key_type": "rsa"
  }'
```

### 3. Add Service

```bash
curl -X POST http://localhost:8000/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "cppm-cluster-https",
    "host": "cppm-pub.example.com",
    "type": "clearpass",
    "cert_pack_id": "clearpass-cert",
    "cert_usage": "HTTPS(RSA)",
    "credential_id": "cppm-prod",
    "additional_nodes": ["cppm-sub1.example.com", "cppm-sub2.example.com"],
    "enabled": true
  }'
```

### 4. Deploy

```bash
curl -X POST http://localhost:8000/api/services/cppm-cluster-https/deploy
```

### 5. Verify

```bash
curl http://localhost:8000/api/services/cppm-cluster-https/health
```
