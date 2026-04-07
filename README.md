# Certificate Manager

A standalone certificate lifecycle management application with ACME (Let's Encrypt) support and Aruba ClearPass deployment capabilities.

## Features

- **ACME Certificate Management**: Automated Let's Encrypt certificate issuance and renewal via Certbot
- **DNS Providers**: Cloudflare, AWS Route53, DigitalOcean, Google Cloud DNS, OVH, DuckDNS
- **HTTP Providers**: Standalone, Webroot, Nginx, Apache
- **ClearPass Deployment**: Automated certificate deployment to Aruba ClearPass clusters
- **Auto-Renewal**: Background scheduler for automatic certificate renewal (configurable)
- **Health Monitoring**: Service health checks with automatic re-deployment on certificate mismatch
- **REST API**: Simple FastAPI-based REST API with interactive documentation
- **Built-in Credentials**: No external dependencies - credentials stored in config file

## Quick Start

### Using Docker Compose (Recommended)

```bash
# Clone or copy this directory
cd cert-manager

# Copy and edit environment file
cp .env.example .env
nano .env

# Start the service
docker compose up -d

# View logs
docker compose logs -f
```

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run the application
uvicorn cert_manager.app:app --reload --host 0.0.0.0 --port 8000
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EDGE_DOMAIN` | `localhost` | Primary domain for nginx certificate path |
| `DATA_DIR` | `/app/data` | Directory for config, certs, and logs |
| `SSL_DIR` | `/etc/letsencrypt` | Certbot letsencrypt directory |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `SCHEDULER_ENABLED` | `true` | Enable background renewal scheduler |
| `SCHEDULER_TIME` | `00:30` | Daily renewal check time (UTC, HH:MM) |
| `NGINX_CONTAINER_NAME` | `nginx` | Docker container name for nginx reload |

### Directory Structure

```
cert-manager/
├── data/
│   ├── config.yaml          # Main configuration file
│   ├── certs/               # Non-edge certificate packs
│   ├── logs/                # Application logs
│   └── backups/             # Config backups (auto-rotated)
└── ssl/
    └── live/                # Edge certificates (shared with nginx)
        └── {domain}/
            ├── fullchain.pem
            └── privkey.pem
```

## API Documentation

Once running, access the interactive API documentation at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check with status info |
| GET | `/api/certs` | List all certificate packs |
| POST | `/api/certs/request` | Request new ACME certificate |
| POST | `/api/certs/upload` | Upload manual certificate |
| POST | `/api/certs/{name}/renew` | Renew existing ACME certificate |
| DELETE | `/api/certs/{name}` | Delete certificate pack |
| GET | `/api/services` | List managed services |
| POST | `/api/services` | Add managed service |
| POST | `/api/services/{name}/deploy` | Deploy cert to service |
| GET | `/api/services/{name}/health` | Check service health |
| GET | `/api/credentials/acme` | List ACME credentials |
| POST | `/api/credentials/acme` | Add ACME credential |
| GET | `/api/credentials/clearpass` | List ClearPass credentials |
| POST | `/api/credentials/clearpass` | Add ClearPass credential |
| GET | `/api/settings` | Get app settings |
| PATCH | `/api/settings` | Update app settings |

## Usage Examples

### 1. Add ACME Credential (Cloudflare)

```bash
curl -X POST http://localhost:8000/api/credentials/acme \
  -H "Content-Type: application/json" \
  -d '{
    "id": "cloudflare-main",
    "name": "Cloudflare DNS",
    "provider": "cloudflare",
    "api_token": "your-cloudflare-api-token",
    "email": "your-email@example.com"
  }'
```

### 2. Request ACME Certificate

```bash
curl -X POST http://localhost:8000/api/certs/request \
  -H "Content-Type: application/json" \
  -d '{
    "pack_name": "my-domain",
    "domains": ["example.com", "*.example.com"],
    "provider": "cloudflare",
    "credential_id": "cloudflare-main",
    "email": "admin@example.com",
    "challenge_type": "dns-01",
    "key_type": "ecdsa",
    "is_edge": true
  }'
```

### 3. Add ClearPass Credential

```bash
curl -X POST http://localhost:8000/api/credentials/clearpass \
  -H "Content-Type: application/json" \
  -d '{
    "id": "cppm-prod",
    "name": "Production ClearPass",
    "host": "clearpass.example.com",
    "client_id": "your-oauth-client-id",
    "client_secret": "your-oauth-client-secret",
    "verify_ssl": false
  }'
```

### 4. Add Managed Service

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

### 5. Deploy Certificate to Service

```bash
curl -X POST http://localhost:8000/api/services/cppm-https/deploy
```

### 6. Check Service Health

```bash
curl http://localhost:8000/api/services/cppm-https/health
```

## ClearPass Integration

### Certificate Usage Types

| Usage | Description |
|-------|-------------|
| `HTTPS(RSA)` | HTTPS server certificate (RSA key) |
| `HTTPS(ECC)` | HTTPS server certificate (ECC key) |
| `RADIUS` | RADIUS/EAP server certificate |
| `RadSec` | RadSec (RADIUS over TLS) certificate |
| `Database` | Database server certificate |

### Multi-Node Clusters

For ClearPass clusters with multiple nodes, specify additional nodes when creating the service:

```json
{
  "name": "cppm-cluster",
  "host": "cppm-node1.example.com",
  "additional_nodes": ["cppm-node2.example.com", "cppm-node3.example.com"],
  ...
}
```

### CA Trust List

When deploying certificates, the application automatically:
1. Extracts CA certificates from the certificate chain
2. Follows AIA (Authority Information Access) to fetch missing parent CAs
3. Uploads missing CA certificates to the ClearPass trust list
4. Updates trust list usage types as needed (EAP, RadSec, Others, etc.)

## Nginx Integration

### Auto-Reload

When `is_edge: true` certificates are renewed, the application automatically sends a SIGHUP signal to the nginx container to reload its configuration. This requires:

1. Docker socket mounted: `/var/run/docker.sock:/var/run/docker.sock:ro`
2. Correct container name: `NGINX_CONTAINER_NAME=nginx`
3. Container has `requests-unixsocket` package installed

### Certificate Path

Edge certificates are saved to `ssl/live/{EDGE_DOMAIN}/` with symlinks created if the pack name differs from the edge domain.

## Background Scheduler

The scheduler runs two independent background tasks:

### Renewal Loop (Daily)
- Runs at configured time (default: 00:30 UTC)
- Checks all ACME certificates with `auto_renew: true`
- Renews certificates within 30 days of expiry
- Reloads nginx for edge certificates
- Auto-deploys to referencing services

### Service Monitor (Every 5 Minutes)
- Health checks all enabled services
- Detects certificate mismatches (local vs remote serial number)
- Auto-deploys on mismatch
- Retries pending/failed ACME requests (max 5 retries)

## Security Considerations

### Production Deployment

For production, consider enabling these security options in `docker-compose.yml`:

```yaml
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
cap_add:
  - NET_BIND_SERVICE
read_only: true
tmpfs:
  - /tmp
  - /app/.cache
```

### Credentials Storage

Credentials are stored in plain text in `data/config.yaml`. For enhanced security:
- Use restrictive file permissions (0600)
- Consider using Docker secrets or external secret management
- Don't commit `config.yaml` to version control

### SSL Verification

ClearPass API calls use `verify=False` by default since ClearPass often uses self-signed certificates. Set `verify_ssl: true` in credentials if you have a valid CA-signed certificate.

## Troubleshooting

### View Logs

```bash
# Docker logs
docker compose logs -f cert-manager

# Application logs
cat data/logs/cert-manager.log
```

### Common Issues

1. **Certbot lock file error**: Automatically cleared and retried
2. **Certificate not found after renewal**: Check certbot logs in `ssl/logs/`
3. **ClearPass deployment failed**: Verify OAuth credentials and API access
4. **Nginx not reloading**: Check Docker socket permissions and container name

### Debug Mode

Enable debug logging:

```bash
LOG_LEVEL=DEBUG docker compose up
```

## License

MIT License - See LICENSE file for details.
