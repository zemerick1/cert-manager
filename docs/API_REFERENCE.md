# API Reference

**Version**: 1.0.0
**Base URL**: `http://localhost:8000`

---

## Table of Contents

1. [Overview](#overview)
2. [Health](#health)
3. [Certificates](#certificates)
4. [Services](#services)
5. [Credentials](#credentials)
6. [Settings](#settings)
7. [Providers](#providers)
8. [Error Handling](#error-handling)

---

## Overview

### Authentication

Currently, the API does not require authentication. For production deployments, consider placing the service behind a reverse proxy with authentication.

### Content Type

All requests and responses use `application/json`.

### Interactive Documentation

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

---

## Health

### GET /api/health

Returns the health status of the application.

**Response**

```json
{
  "status": "healthy",
  "scheduler_running": true,
  "total_cert_packs": 3,
  "total_services": 2,
  "certs_expiring_soon": 0,
  "next_renewal_check": "2024-01-16T00:30:00+00:00",
  "callback_base": "http://certs.example.com"
}
```

**Response Fields**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always "healthy" if responding |
| `scheduler_running` | boolean | Whether background scheduler is active |
| `total_cert_packs` | integer | Number of certificate packs |
| `total_services` | integer | Number of managed services |
| `certs_expiring_soon` | integer | Certs expiring within 30 days |
| `next_renewal_check` | string | ISO timestamp of next scheduled check |
| `callback_base` | string | URL prefix ClearPass uses to download a certificate (`http://{EDGE_DOMAIN}`, port 80) |

---

## Certificates

### GET /api/certs

Lists all certificate packs.

**Response**

```json
[
  {
    "name": "my-domain",
    "domains": ["example.com", "*.example.com"],
    "source": "acme",
    "not_before": "2024-01-01T00:00:00+00:00",
    "not_after": "2024-04-01T00:00:00+00:00",
    "days_remaining": 75,
    "issuer": "CN=R3,O=Let's Encrypt,C=US",
    "subject": "CN=example.com",
    "serial_number": "ABC123...",
    "key_type": "ecc",
    "auto_renew": true,
    "is_edge": true,
    "provider": "cloudflare",
    "challenge_type": "dns-01",
    "credential_id": "cloudflare-main",
    "last_renewal": "2024-01-01T00:30:00+00:00",
    "last_renewal_status": "SUCCESS"
  }
]
```

---

### GET /api/certs/{pack_name}

Gets a specific certificate pack.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pack_name` | string | Certificate pack name |

**Response**

Same as single item in list response.

**Errors**

| Code | Description |
|------|-------------|
| 404 | Certificate pack not found |

---

### POST /api/certs/request

Requests a new ACME certificate from Let's Encrypt.

**Request Body**

```json
{
  "pack_name": "my-domain",
  "domains": ["example.com", "*.example.com"],
  "provider": "cloudflare",
  "credential_id": "cloudflare-main",
  "email": "admin@example.com",
  "challenge_type": "dns-01",
  "key_type": "ecdsa",
  "is_edge": true
}
```

**Request Fields**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `pack_name` | string | Yes | - | Unique name for the certificate pack |
| `domains` | array | Yes | - | List of domain names |
| `provider` | string | Yes | - | ACME provider (see Providers) |
| `credential_id` | string | Yes | - | ID of ACME credential |
| `email` | string | Yes | - | ACME account email |
| `challenge_type` | string | No | `dns-01` | Challenge type |
| `key_type` | string | No | `ecdsa` | Key type (`rsa` or `ecdsa`) |
| `is_edge` | boolean | No | `false` | Save as edge certificate |

**Response**

```json
{
  "success": true,
  "message": "Certificate obtained and saved as 'my-domain'.",
  "data": null
}
```

This call blocks until Certbot finishes. Use the job endpoints below to return immediately and poll for progress.

---

### POST /api/certs/jobs

Starts the same certificate request as `POST /api/certs/request` and returns a job. The job record lives in the API process. A restart drops it. The certificate files and `config.yaml` are still written by the request itself.

**Request Body**

Same fields as `POST /api/certs/request`.

**Response**

```json
{
  "job_id": "b7e1c0a2f4d64e0a9c1b2d3e4f506172",
  "pack_name": "my-domain",
  "kind": "request",
  "status": "PENDING",
  "progress": [],
  "success": null,
  "message": null
}
```

`status` moves from `PENDING` to `RUNNING`, then `SUCCESS` or `FAILED`. `progress` collects the lines Certbot emits while it waits on DNS.

**Errors**

| Code | Description |
|------|-------------|
| 409 | A job for this pack is already pending or running |

---

### GET /api/certs/jobs

Lists jobs started in this process, newest first.

---

### GET /api/certs/jobs/{job_id}

Returns one job, including progress lines and the final message.

**Errors**

| Code | Description |
|------|-------------|
| 404 | Job not found |

---

### POST /api/certs/{pack_name}/jobs

Starts a renewal for an existing ACME pack and returns a job. Poll `GET /api/certs/jobs/{job_id}`. `POST /api/certs/{pack_name}/renew` still blocks until Certbot finishes.

**Errors**

| Code | Description |
|------|-------------|
| 404 | Certificate pack not found |
| 400 | Pack is not an ACME certificate |
| 409 | A job for this pack is already pending or running |

---

### POST /api/certs/upload

Uploads a manual certificate.

**Request Body**

```json
{
  "pack_name": "manual-cert",
  "fullchain": "-----BEGIN CERTIFICATE-----\n...",
  "privkey": "-----BEGIN PRIVATE KEY-----\n...",
  "is_edge": false
}
```

**Request Fields**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pack_name` | string | Yes | Unique name for the certificate pack |
| `fullchain` | string | Yes | PEM-encoded certificate chain |
| `privkey` | string | Yes | PEM-encoded private key |
| `is_edge` | boolean | No | Save as edge certificate |

**Response**

```json
{
  "success": true,
  "message": "Certificate uploaded as 'manual-cert'",
  "data": null
}
```

---

### POST /api/certs/{pack_name}/renew

Renews an existing ACME certificate.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pack_name` | string | Certificate pack name |

**Response**

```json
{
  "success": true,
  "message": "Certificate obtained and saved as 'my-domain'.",
  "data": null
}
```

**Errors**

| Code | Description |
|------|-------------|
| 400 | Pack is not an ACME certificate |

---

### DELETE /api/certs/{pack_name}

Deletes a certificate pack.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pack_name` | string | Certificate pack name |

**Response**

```json
{
  "success": true,
  "message": "Certificate pack 'my-domain' deleted",
  "data": null
}
```

**Errors**

| Code | Description |
|------|-------------|
| 404 | Certificate pack not found |

---

## Services

### GET /api/services

Lists all managed services.

**Response**

```json
[
  {
    "name": "cppm-https",
    "host": "clearpass.example.com",
    "type": "clearpass",
    "cert_pack_id": "my-domain",
    "cert_usage": "HTTPS(RSA)",
    "enabled": true,
    "credential_id": "cppm-prod",
    "additional_nodes": [],
    "health_status": {
      "success": true,
      "expiry": "2024-04-01",
      "days_remaining": 75,
      "subject": "CN=example.com",
      "issuer": "CN=R3,O=Let's Encrypt,C=US"
    },
    "last_renewal": null
  }
]
```

---

### GET /api/services/{service_name}

Gets a specific service.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `service_name` | string | Service name |

**Errors**

| Code | Description |
|------|-------------|
| 404 | Service not found |

---

### POST /api/services

Adds a new managed service.

**Request Body**

```json
{
  "name": "cppm-https",
  "host": "clearpass.example.com",
  "type": "clearpass",
  "cert_pack_id": "my-domain",
  "cert_usage": "HTTPS(RSA)",
  "enabled": true,
  "credential_id": "cppm-prod",
  "additional_nodes": ["cppm-node2.example.com"]
}
```

**Request Fields**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | - | Unique service name |
| `host` | string | Yes | - | Service hostname |
| `type` | string | No | `clearpass` | Service type |
| `cert_pack_id` | string | No | - | Associated certificate pack |
| `cert_usage` | string | No | `HTTPS(RSA)` | Certificate usage type |
| `enabled` | boolean | No | `true` | Enable service monitoring |
| `credential_id` | string | No | - | ClearPass credential ID |
| `additional_nodes` | array | No | `[]` | Additional cluster nodes |

**Certificate Usage Types**

| Value | Description |
|-------|-------------|
| `HTTPS(RSA)` | HTTPS with RSA certificate |
| `HTTPS(ECC)` | HTTPS with ECC certificate |
| `RADIUS` | RADIUS/EAP server |
| `RadSec` | RadSec (RADIUS over TLS) |
| `Database` | Database server |

**Response**

Returns the created service object.

**Errors**

| Code | Description |
|------|-------------|
| 400 | Service name already exists |

---

### PATCH /api/services/{service_name}

Updates an existing service.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `service_name` | string | Service name |

**Request Body**

```json
{
  "cert_pack_id": "new-cert",
  "enabled": false
}
```

All fields are optional. Only provided fields are updated.

**Response**

Returns the updated service object.

**Errors**

| Code | Description |
|------|-------------|
| 404 | Service not found |

---

### DELETE /api/services/{service_name}

Deletes a managed service.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `service_name` | string | Service name |

**Response**

```json
{
  "success": true,
  "message": "Service 'cppm-https' deleted",
  "data": null
}
```

**Errors**

| Code | Description |
|------|-------------|
| 404 | Service not found |

---

### POST /api/services/{service_name}/deploy

Deploys certificate to a managed service.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `service_name` | string | Service name |

**Response**

`data.stage` names the step that produced the result: `config`, `pfx`, `oauth`, `cluster`, or `install`. `data.nodes` is one entry per ClearPass host. A CA trust failure is listed on the node and in the message, including when the certificate install itself succeeded.

```json
{
  "success": false,
  "message": "ClearPass authentication failed (401): invalid_client",
  "data": {
    "stage": "oauth",
    "nodes": [
      {
        "host": "https://clearpass.example.com",
        "success": false,
        "stage": "oauth",
        "message": "ClearPass authentication failed (401): invalid_client",
        "ca_trust_errors": []
      }
    ]
  }
}
```

An install rejection includes the HTTP status and the URL ClearPass was told to download. The same text is on the matching node. A missing certificate pack stays HTTP 200 with `success: false`.

**Errors**

| Code | Description |
|------|-------------|
| 404 | Service not found |

---

### GET /api/services/{service_name}/health

Checks the health of a managed service.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `service_name` | string | Service name |

**Response**

```json
{
  "success": true,
  "message": "Health check complete",
  "data": {
    "success": true,
    "expiry": "2024-04-01",
    "days_remaining": 75,
    "subject": "CN=example.com",
    "issuer": "CN=R3,O=Let's Encrypt,C=US",
    "serial_number": "ABC123..."
  }
}
```

**Errors**

| Code | Description |
|------|-------------|
| 404 | Service not found |

---

## Credentials

### GET /api/credentials/acme

Lists all ACME credentials (without secrets).

**Response**

```json
[
  {
    "id": "cloudflare-main",
    "name": "Cloudflare DNS",
    "provider": "cloudflare",
    "email": "admin@example.com"
  }
]
```

---

### POST /api/credentials/acme

Adds a new ACME credential.

**Request Body (Cloudflare)**

```json
{
  "id": "cloudflare-main",
  "name": "Cloudflare DNS",
  "provider": "cloudflare",
  "api_token": "your-api-token",
  "email": "admin@example.com"
}
```

**Request Body (Route53)**

```json
{
  "id": "route53-aws",
  "name": "AWS Route53",
  "provider": "route53",
  "access_key_id": "AKIAIOSFODNN7EXAMPLE",
  "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
  "region": "us-east-1"
}
```

**Request Body (DigitalOcean)**

```json
{
  "id": "do-dns",
  "name": "DigitalOcean DNS",
  "provider": "digitalocean",
  "api_token": "dop_v1_your-token"
}
```

**Response**

```json
{
  "success": true,
  "message": "ACME credential 'cloudflare-main' saved",
  "data": null
}
```

---

### POST /api/credentials/acme/test

Tests a Cloudflare API token without saving it. The check calls Cloudflare's token verify endpoint, lists visible zones, and reads one DNS record. It does not create a DNS record. Zone DNS Edit is still required for issuance and is not proven by this call.

**Request Body**

```json
{
  "api_token": "your-api-token"
}
```

**Response**

```json
{
  "success": true,
  "message": "Cloudflare token is active. It can see 1 zone(s): example.com. DNS read succeeded on example.com. Certificate issuance also needs Zone:DNS:Edit on that zone.",
  "data": {
    "token_status": "active",
    "zones": ["example.com"],
    "dns_read": true
  }
}
```

The token is not echoed in the response.

---

### POST /api/credentials/acme/{credential_id}/test

Tests a saved ACME credential. Live checks run for Cloudflare tokens. Other providers return `success: false` with the provider name. Saved secrets are not included in the response.

**Errors**

| Code | Description |
|------|-------------|
| 404 | Credential not found |

---

### DELETE /api/credentials/acme/{credential_id}

Deletes an ACME credential.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `credential_id` | string | Credential ID |

**Response**

```json
{
  "success": true,
  "message": "ACME credential 'cloudflare-main' deleted",
  "data": null
}
```

**Errors**

| Code | Description |
|------|-------------|
| 404 | Credential not found |

---

### GET /api/credentials/clearpass

Lists all ClearPass credentials (without secrets).

**Response**

```json
[
  {
    "id": "cppm-prod",
    "name": "Production ClearPass",
    "host": "clearpass.example.com"
  }
]
```

---

### POST /api/credentials/clearpass

Adds a new ClearPass credential.

**Request Body**

```json
{
  "id": "cppm-prod",
  "name": "Production ClearPass",
  "host": "clearpass.example.com",
  "client_id": "your-oauth-client-id",
  "client_secret": "your-oauth-client-secret",
  "verify_ssl": false
}
```

**Request Fields**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique credential ID |
| `name` | string | Yes | Display name |
| `host` | string | Yes | ClearPass hostname |
| `client_id` | string | Yes | OAuth client ID |
| `client_secret` | string | Yes | OAuth client secret |
| `verify_ssl` | boolean | No | Verify SSL certificate |

**Response**

```json
{
  "success": true,
  "message": "ClearPass credential 'cppm-prod' saved",
  "data": null
}
```

---

### POST /api/credentials/clearpass/test

Signs in to ClearPass with an OAuth client, lists cluster nodes, and reads the DNS name on each installed server certificate. Nothing is saved. The access token and client secret are not returned.

A missing certificate has an empty `names` list and does not fail the login. The usages are `HTTPS(RSA)`, `HTTPS(ECC)`, `RADIUS` (802.1X / EAP), `RadSec`, and `Database`. `names` is the DNS subject alternative names, or the common name when the certificate has no DNS name. When nodes disagree, `servers` lists each node's names.

**Request Body**

```json
{
  "host": "clearpass.example.com",
  "client_id": "cert-manager",
  "client_secret": "your-oauth-client-secret"
}
```

**Response**

```json
{
  "success": true,
  "message": "Authenticated to https://clearpass.example.com. Found 1 cluster node(s): cppm1.",
  "data": {
    "stage": "ok",
    "host": "https://clearpass.example.com",
    "servers": ["cppm1"],
    "certificates": [
      {
        "usage": "HTTPS(RSA)",
        "label": "HTTPS (RSA)",
        "names": ["clearpass.example.com"],
        "servers": [{"server": "cppm1", "names": ["clearpass.example.com"]}]
      },
      {
        "usage": "HTTPS(ECC)",
        "label": "HTTPS (ECC)",
        "names": [],
        "servers": [{"server": "cppm1", "names": []}]
      },
      {
        "usage": "RADIUS",
        "label": "RADIUS / EAP",
        "names": ["radius.example.com"],
        "servers": [{"server": "cppm1", "names": ["radius.example.com"]}]
      },
      {
        "usage": "RadSec",
        "label": "RadSec",
        "names": [],
        "servers": [{"server": "cppm1", "names": []}]
      },
      {
        "usage": "Database",
        "label": "Database",
        "names": ["db.example.com"],
        "servers": [{"server": "cppm1", "names": ["db.example.com"]}]
      }
    ]
  }
}
```

`data.stage` is `config`, `oauth`, or `cluster` when the test fails. An OAuth failure includes the ClearPass status code and response body. Certificate names are only present after a successful login and cluster lookup.

---

### POST /api/credentials/clearpass/{credential_id}/test

Runs the same check with a saved ClearPass credential.

**Errors**

| Code | Description |
|------|-------------|
| 404 | Credential not found |

---

### DELETE /api/credentials/clearpass/{credential_id}

Deletes a ClearPass credential.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `credential_id` | string | Credential ID |

**Response**

```json
{
  "success": true,
  "message": "ClearPass credential 'cppm-prod' deleted",
  "data": null
}
```

**Errors**

| Code | Description |
|------|-------------|
| 404 | Credential not found |

---

## Settings

### GET /api/settings

Gets application settings.

**Response**

```json
{
  "log_level": "INFO",
  "scheduler_time": "00:30"
}
```

---

### PATCH /api/settings

Updates application settings.

**Request Body**

```json
{
  "log_level": "DEBUG",
  "scheduler_time": "02:00"
}
```

All fields are optional.

**Response**

```json
{
  "success": true,
  "message": "Settings updated",
  "data": null
}
```

---

## Providers

### GET /api/providers/acme

Lists available ACME providers.

**Response**

```json
[
  {"id": "cloudflare", "name": "Cloudflare", "challenge_type": "dns-01"},
  {"id": "route53", "name": "AWS Route53", "challenge_type": "dns-01"},
  {"id": "digitalocean", "name": "DigitalOcean", "challenge_type": "dns-01"},
  {"id": "google", "name": "Google Cloud DNS", "challenge_type": "dns-01"},
  {"id": "ovh", "name": "OVH", "challenge_type": "dns-01"},
  {"id": "duckdns", "name": "DuckDNS", "challenge_type": "dns-01"},
  {"id": "standalone", "name": "Standalone", "challenge_type": "http-01"},
  {"id": "webroot", "name": "Webroot", "challenge_type": "http-01"},
  {"id": "nginx", "name": "Nginx", "challenge_type": "http-01"},
  {"id": "apache", "name": "Apache", "challenge_type": "http-01"}
]
```

---

## Error Handling

### Error Response Format

```json
{
  "detail": "Error message here"
}
```

### HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 400 | Bad request (validation error) |
| 404 | Resource not found |
| 422 | Unprocessable entity (validation error) |
| 500 | Internal server error |

### Validation Errors

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "email"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

---

## Rate Limiting

No rate limiting is implemented. For production deployments, consider adding rate limiting at the reverse proxy level.

---

## Versioning

The API currently does not use versioning. Future breaking changes will be announced with a migration path.
