# Deployment Guide

This guide covers deploying the Certificate Manager in various environments.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Docker Compose (Recommended)](#docker-compose-recommended)
3. [Docker Standalone](#docker-standalone)
4. [Kubernetes](#kubernetes)
5. [Bare Metal / VM](#bare-metal--vm)
6. [Reverse Proxy Configuration](#reverse-proxy-configuration)
7. [High Availability](#high-availability)
8. [Backup and Recovery](#backup-and-recovery)

---

## Prerequisites

### System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 1 core | 2 cores |
| RAM | 512 MB | 1 GB |
| Disk | 1 GB | 5 GB |
| Network | Outbound HTTPS | Outbound HTTPS |

### Network Requirements

The application requires outbound access to:

| Service | Port | Purpose |
|---------|------|---------|
| Let's Encrypt | 443 | ACME certificate issuance |
| DNS Providers | 443 | DNS-01 challenge (Cloudflare, Route53, etc.) |
| ClearPass | 443 | Certificate deployment |

### Software Requirements

- Docker 20.10+ and Docker Compose 2.0+ (for containerized deployment)
- Python 3.11+ (for bare metal deployment)
- Certbot (installed automatically in container)

---

## Docker Compose (Recommended)

### Basic Setup

1. **Clone the repository**

```bash
git clone https://github.com/your-org/cert-manager.git
cd cert-manager
```

2. **Create environment file**

```bash
cp .env.example .env
nano .env
```

Edit `.env`:

```bash
EDGE_DOMAIN=your-domain.example.com
LOG_LEVEL=INFO
SCHEDULER_ENABLED=true
SCHEDULER_TIME=00:30
NGINX_CONTAINER_NAME=nginx
```

3. **Create data directories**

```bash
mkdir -p data ssl
touch data/.gitkeep ssl/.gitkeep
```

4. **Start the service**

```bash
docker compose up -d
```

5. **Verify deployment**

```bash
curl http://localhost:8000/api/health
```

### Production Configuration

For production, update `docker-compose.yml`:

```yaml
version: "3.8"

services:
  cert-manager:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: cert-manager
    restart: always
    ports:
      - "127.0.0.1:8000:8000"  # Bind to localhost only
    environment:
      - EDGE_DOMAIN=${EDGE_DOMAIN}
      - DATA_DIR=/app/data
      - SSL_DIR=/etc/letsencrypt
      - LOG_LEVEL=WARNING
      - SCHEDULER_ENABLED=true
      - SCHEDULER_TIME=00:30
      - NGINX_CONTAINER_NAME=${NGINX_CONTAINER_NAME:-nginx}
    volumes:
      - ./data:/app/data
      - ./ssl:/etc/letsencrypt
      - /var/run/docker.sock:/var/run/docker.sock:ro
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
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### With Nginx Reverse Proxy

Create a `docker-compose.yml` that includes nginx:

```yaml
version: "3.8"

services:
  cert-manager:
    build: .
    container_name: cert-manager
    restart: unless-stopped
    expose:
      - "8000"
    environment:
      - EDGE_DOMAIN=${EDGE_DOMAIN}
      - DATA_DIR=/app/data
      - SSL_DIR=/etc/letsencrypt
      - NGINX_CONTAINER_NAME=nginx
    volumes:
      - ./data:/app/data
      - ./ssl:/etc/letsencrypt
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - internal

  nginx:
    image: nginx:alpine
    container_name: nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./ssl:/etc/letsencrypt:ro
    networks:
      - internal
      - external
    depends_on:
      - cert-manager

networks:
  internal:
    driver: bridge
  external:
    driver: bridge
```

---

## Docker Standalone

### Build Image

```bash
docker build -t cert-manager:latest .
```

### Run Container

```bash
docker run -d \
  --name cert-manager \
  --restart unless-stopped \
  -p 8000:8000 \
  -e EDGE_DOMAIN=your-domain.example.com \
  -e LOG_LEVEL=INFO \
  -e SCHEDULER_ENABLED=true \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/ssl:/etc/letsencrypt \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  cert-manager:latest
```

### Container Management

```bash
# View logs
docker logs -f cert-manager

# Restart container
docker restart cert-manager

# Stop container
docker stop cert-manager

# Remove container
docker rm cert-manager
```

---

## Kubernetes

### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cert-manager-config
  namespace: cert-manager
data:
  EDGE_DOMAIN: "your-domain.example.com"
  LOG_LEVEL: "INFO"
  SCHEDULER_ENABLED: "true"
  SCHEDULER_TIME: "00:30"
```

### PersistentVolumeClaim

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: cert-manager-data
  namespace: cert-manager
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi

---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: cert-manager-ssl
  namespace: cert-manager
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cert-manager
  namespace: cert-manager
spec:
  replicas: 1  # Only 1 replica - scheduler must be singleton
  selector:
    matchLabels:
      app: cert-manager
  template:
    metadata:
      labels:
        app: cert-manager
    spec:
      containers:
        - name: cert-manager
          image: cert-manager:latest
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: cert-manager-config
          env:
            - name: DATA_DIR
              value: /app/data
            - name: SSL_DIR
              value: /etc/letsencrypt
          volumeMounts:
            - name: data
              mountPath: /app/data
            - name: ssl
              mountPath: /etc/letsencrypt
          livenessProbe:
            httpGet:
              path: /api/health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /api/health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: cert-manager-data
        - name: ssl
          persistentVolumeClaim:
            claimName: cert-manager-ssl
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: cert-manager
  namespace: cert-manager
spec:
  selector:
    app: cert-manager
  ports:
    - protocol: TCP
      port: 8000
      targetPort: 8000
  type: ClusterIP
```

### Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: cert-manager
  namespace: cert-manager
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
spec:
  rules:
    - host: cert-manager.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: cert-manager
                port:
                  number: 8000
```

---

## Bare Metal / VM

### System Preparation

```bash
# Install Python 3.11+
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip

# Install Certbot
sudo apt install -y certbot

# Create application user
sudo useradd -r -s /bin/false certmgr
```

### Application Setup

```bash
# Create directories
sudo mkdir -p /opt/cert-manager
sudo mkdir -p /var/lib/cert-manager/data
sudo mkdir -p /etc/letsencrypt

# Clone repository
cd /opt/cert-manager
sudo git clone https://github.com/your-org/cert-manager.git .

# Create virtual environment
sudo python3.11 -m venv venv
sudo ./venv/bin/pip install -e .

# Set permissions
sudo chown -R certmgr:certmgr /opt/cert-manager
sudo chown -R certmgr:certmgr /var/lib/cert-manager
sudo chown -R certmgr:certmgr /etc/letsencrypt
```

### Systemd Service

Create `/etc/systemd/system/cert-manager.service`:

```ini
[Unit]
Description=Certificate Manager
After=network.target

[Service]
Type=simple
User=certmgr
Group=certmgr
WorkingDirectory=/opt/cert-manager
Environment="EDGE_DOMAIN=your-domain.example.com"
Environment="DATA_DIR=/var/lib/cert-manager/data"
Environment="SSL_DIR=/etc/letsencrypt"
Environment="LOG_LEVEL=INFO"
Environment="SCHEDULER_ENABLED=true"
Environment="SCHEDULER_TIME=00:30"
ExecStart=/opt/cert-manager/venv/bin/uvicorn cert_manager.app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable cert-manager
sudo systemctl start cert-manager
sudo systemctl status cert-manager
```

---

## Reverse Proxy Configuration

### Nginx

```nginx
upstream cert-manager {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name cert-manager.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name cert-manager.example.com;

    ssl_certificate /etc/letsencrypt/live/cert-manager.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/cert-manager.example.com/privkey.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";

    location / {
        proxy_pass http://cert-manager;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

### Apache

```apache
<VirtualHost *:80>
    ServerName cert-manager.example.com
    Redirect permanent / https://cert-manager.example.com/
</VirtualHost>

<VirtualHost *:443>
    ServerName cert-manager.example.com

    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/cert-manager.example.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/cert-manager.example.com/privkey.pem

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    <Location />
        Require all granted
    </Location>
</VirtualHost>
```

### Traefik

```yaml
# traefik.yml
http:
  routers:
    cert-manager:
      rule: "Host(`cert-manager.example.com`)"
      service: cert-manager
      tls:
        certResolver: letsencrypt

  services:
    cert-manager:
      loadBalancer:
        servers:
          - url: "http://cert-manager:8000"
```

---

## High Availability

### Important Considerations

The Certificate Manager includes a background scheduler that should run as a **singleton**. Running multiple instances with the scheduler enabled will cause:

- Duplicate renewal attempts
- Race conditions in certificate deployment
- Conflicting health check operations

### Recommended HA Setup

1. **Single Active Instance** with health monitoring
2. **Shared Storage** for data and certificates
3. **External Monitoring** for failover

### Active-Passive with Keepalived

```bash
# On both nodes
apt install keepalived

# /etc/keepalived/keepalived.conf (master)
vrrp_script chk_certmgr {
    script "/usr/bin/curl -sf http://localhost:8000/api/health"
    interval 5
    weight -20
}

vrrp_instance VI_CERTMGR {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 100

    virtual_ipaddress {
        192.168.1.100/24
    }

    track_script {
        chk_certmgr
    }
}
```

---

## Backup and Recovery

### Automated Backups

The application automatically backs up `config.yaml` before each write, keeping the last 20 versions in `data/backups/`.

### Manual Backup

```bash
# Backup data directory
tar -czf cert-manager-backup-$(date +%Y%m%d).tar.gz data/ ssl/

# Backup to remote location
rsync -avz data/ user@backup-server:/backups/cert-manager/data/
rsync -avz ssl/ user@backup-server:/backups/cert-manager/ssl/
```

### Recovery

```bash
# Stop the service
docker compose down

# Restore data
tar -xzf cert-manager-backup-20240115.tar.gz

# Restart
docker compose up -d
```

### Critical Files to Backup

| Path | Description |
|------|-------------|
| `data/config.yaml` | All configuration including credentials |
| `ssl/live/` | Active certificates |
| `ssl/archive/` | Certificate history |
| `ssl/renewal/` | Certbot renewal configuration |
| `ssl/accounts/` | ACME account keys |

---

## Monitoring

### Health Endpoint

```bash
# Basic health check
curl http://localhost:8000/api/health

# Expected response
{
  "status": "healthy",
  "scheduler_running": true,
  "total_cert_packs": 3,
  "total_services": 2,
  "certs_expiring_soon": 0,
  "next_renewal_check": "2024-01-16T00:30:00+00:00"
}
```

### Prometheus Metrics (Optional)

Add prometheus-fastapi-instrumentator for metrics:

```python
# In app.py
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)
```

### Log Monitoring

```bash
# Docker logs
docker compose logs -f --tail=100 cert-manager

# Application logs
tail -f data/logs/cert-manager.log
```

### Alerting Suggestions

Set up alerts for:

- `certs_expiring_soon > 0` - Certificates expiring within 30 days
- `scheduler_running == false` - Scheduler stopped
- Health check failures
- HTTP 5xx errors in logs
