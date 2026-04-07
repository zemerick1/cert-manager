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
  "next_renewal_check": "2024-01-16T00:30:00+00:00"
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

```json
{
  "success": true,
  "message": "Deployment successful",
  "data": null
}
```

**Errors**

| Code | Description |
|------|-------------|
| 404 | Service not found |
| 400 | No certificate pack assigned |

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
