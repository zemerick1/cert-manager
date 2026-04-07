# Troubleshooting Guide

Solutions for common issues with Certificate Manager.

---

## Table of Contents

1. [Quick Diagnostics](#quick-diagnostics)
2. [Startup Issues](#startup-issues)
3. [ACME / Let's Encrypt Issues](#acme--lets-encrypt-issues)
4. [ClearPass Deployment Issues](#clearpass-deployment-issues)
5. [Scheduler Issues](#scheduler-issues)
6. [Certificate Issues](#certificate-issues)
7. [Docker Issues](#docker-issues)
8. [Log Analysis](#log-analysis)
9. [Getting Help](#getting-help)

---

## Quick Diagnostics

### Health Check

```bash
curl http://localhost:8000/api/health
```

Expected healthy response:
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

### Enable Debug Logging

```bash
# Docker Compose
LOG_LEVEL=DEBUG docker compose up

# Or edit .env
echo "LOG_LEVEL=DEBUG" >> .env
docker compose restart
```

### View Logs

```bash
# Docker logs
docker compose logs -f --tail=100 cert-manager

# Application log file
cat data/logs/cert-manager.log

# Certbot logs
cat ssl/logs/letsencrypt.log
```

---

## Startup Issues

### Application Won't Start

**Symptoms**: Container exits immediately, "Address already in use"

**Check port availability**:
```bash
# Check if port 8000 is in use
ss -tlnp | grep 8000
lsof -i :8000
```

**Solutions**:
- Change port mapping in docker-compose.yml
- Stop conflicting service
- Use different port: `-p 8001:8000`

### Configuration Error on Startup

**Symptoms**: "Error loading config", "YAML parse error"

**Check config file**:
```bash
# Validate YAML syntax
python3 -c "import yaml; yaml.safe_load(open('data/config.yaml'))"

# Check file permissions
ls -la data/config.yaml
```

**Solutions**:
- Restore from backup: `cp data/backups/config_*.yaml data/config.yaml`
- Check YAML indentation (use spaces, not tabs)
- Verify no special characters in strings

### Permission Denied Errors

**Symptoms**: "Permission denied", can't write to data directory

**Check ownership**:
```bash
ls -la data/
ls -la ssl/
```

**Solutions**:
```bash
# Fix ownership (adjust UID if needed)
sudo chown -R 1000:1000 data/ ssl/

# Fix permissions
chmod -R 755 data/ ssl/
chmod 600 data/config.yaml
```

---

## ACME / Let's Encrypt Issues

### Certificate Request Failed

**Symptoms**: "Error obtaining certificate", "Challenge failed"

#### DNS-01 Challenge Failures

**Check DNS propagation**:
```bash
# Check TXT record
dig _acme-challenge.example.com TXT +short

# Query specific nameservers
dig @8.8.8.8 _acme-challenge.example.com TXT +short
dig @1.1.1.1 _acme-challenge.example.com TXT +short
```

**Common causes**:
1. **API credentials invalid**: Verify provider credentials
2. **DNS propagation delay**: Wait and retry
3. **Wrong zone**: Check domain is in correct DNS zone
4. **CAA records**: Check for restrictive CAA records

**Check CAA records**:
```bash
dig example.com CAA +short
# Should be empty or include: 0 issue "letsencrypt.org"
```

#### HTTP-01 Challenge Failures

**Check port 80 accessibility**:
```bash
# From external host
curl -I http://example.com/.well-known/acme-challenge/test
```

**Common causes**:
1. **Port 80 blocked**: Check firewall
2. **Wrong webroot**: Verify webroot path
3. **Server not responding**: Check web server status

### Rate Limit Exceeded

**Symptoms**: "too many certificates already issued", "rate limit"

**Let's Encrypt rate limits**:
- 50 certificates per registered domain per week
- 5 duplicate certificates per week
- 5 failed validations per account per hour

**Solutions**:
- Wait for rate limit to reset
- Use staging server for testing: Add `--staging` to certbot commands
- Combine domains into fewer certificates

### Certbot Lock File Error

**Symptoms**: "Another instance of Certbot is already running"

**Solution**:
```bash
# Remove lock file (automatic in application)
rm -f /etc/letsencrypt/.certbot.lock
rm -f ssl/.certbot.lock
```

### Invalid Credentials

**Symptoms**: "Authentication failed", "Invalid API token"

**Verify credentials**:

For Cloudflare:
```bash
curl -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

For AWS Route53:
```bash
aws sts get-caller-identity --profile your-profile
```

---

## ClearPass Deployment Issues

### Authentication Failed

**Symptoms**: "401 Unauthorized", "invalid_client"

**Test OAuth manually**:
```bash
curl -X POST "https://clearpass.example.com/api/oauth" \
  -H "Content-Type: application/json" \
  -d '{
    "grant_type": "client_credentials",
    "client_id": "your-client-id",
    "client_secret": "your-secret"
  }'
```

**Solutions**:
1. Verify client_id and client_secret are correct
2. Check API client is enabled in ClearPass
3. Ensure grant type is "Client Credentials"
4. Verify network connectivity

### Certificate Upload Failed

**Symptoms**: "Failed to upload certificate", "Invalid PFX"

**Check certificate**:
```bash
# Verify certificate
openssl x509 -in data/certs/my-pack/fullchain.pem -text -noout

# Verify key matches certificate
openssl x509 -noout -modulus -in fullchain.pem | md5sum
openssl rsa -noout -modulus -in privkey.pem | md5sum
# Should match
```

**Solutions**:
1. Ensure certificate chain is complete
2. Verify private key is not encrypted
3. Check certificate is not expired
4. Ensure file encoding is correct (PEM format)

### Installation Failed

**Symptoms**: Certificate uploads but doesn't install

**Check ClearPass**:
1. Log in to ClearPass
2. Go to Administration > Certificates > Server Certificates
3. Look for the uploaded certificate
4. Check certificate properties

**Solutions**:
1. Verify certificate usage type is correct
2. Check key type matches (RSA vs ECC)
3. Ensure no certificate lock on that usage
4. Restart ClearPass services if needed

### SSL Verification Errors

**Symptoms**: "SSL: CERTIFICATE_VERIFY_FAILED"

**Solutions**:
```bash
# Option 1: Disable verification (common for self-signed)
# Set in credentials: verify_ssl: false

# Option 2: Add CA certificate
# Add ClearPass CA to system trust
sudo cp clearpass-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

### Cluster Replication Issues

**Symptoms**: Publisher has cert but subscribers don't

**Check replication status**:
1. ClearPass Admin > Server Manager > Server Configuration
2. Check replication status for each node
3. Look for replication errors

**Solutions**:
1. Wait for replication (5-10 minutes)
2. Manually trigger replication
3. Check network between nodes
4. Verify disk space on subscribers

---

## Scheduler Issues

### Scheduler Not Running

**Symptoms**: `scheduler_running: false` in health check

**Check environment**:
```bash
echo $SCHEDULER_ENABLED
# Should be "true"
```

**Check logs**:
```bash
grep -i scheduler data/logs/cert-manager.log
```

**Solutions**:
1. Verify SCHEDULER_ENABLED=true in environment
2. Check for startup errors in logs
3. Restart the application

### Certificates Not Auto-Renewing

**Symptoms**: Certificates expire despite auto_renew: true

**Checklist**:
1. Is scheduler running? Check health endpoint
2. Is auto_renew enabled for the cert? Check config
3. Is the cert within renewal window? (30 days before expiry)
4. Are there ACME errors? Check logs

**Force renewal**:
```bash
curl -X POST http://localhost:8000/api/certs/my-pack/renew
```

### Wrong Renewal Time

**Symptoms**: Renewals happen at unexpected time

**Check timezone**:
- Scheduler uses UTC time
- Convert your local time: `date -u`

**Adjust schedule**:
```bash
# Set to 2 AM local time (if UTC-8)
SCHEDULER_TIME=10:00
```

---

## Certificate Issues

### Certificate Not Found

**Symptoms**: "Certificate pack not found"

**Check file system**:
```bash
# Edge certificates
ls -la ssl/live/

# Non-edge certificates
ls -la data/certs/
```

**Check configuration**:
```bash
grep -A5 "pack-name" data/config.yaml
```

### Certificate Chain Incomplete

**Symptoms**: "certificate verify failed", SSL errors on clients

**Check chain**:
```bash
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt fullchain.pem

# Check chain order
openssl crl2pkcs7 -nocrl -certfile fullchain.pem | \
  openssl pkcs7 -print_certs -noout
```

**Solutions**:
1. Re-request certificate (usually fixes chain)
2. Manually append CA cert to fullchain.pem

### Expired Certificate

**Symptoms**: SSL warnings, services failing

**Check expiry**:
```bash
openssl x509 -enddate -noout -in fullchain.pem
```

**Force renewal**:
```bash
curl -X POST http://localhost:8000/api/certs/pack-name/renew
```

### Wrong Key Type

**Symptoms**: "key type mismatch", deployment fails

**Check key type**:
```bash
# RSA key
openssl rsa -in privkey.pem -text -noout | head -1
# Output: RSA Private-Key: (2048 bit, 2 primes)

# EC key
openssl ec -in privkey.pem -text -noout | head -1
# Output: read EC key
```

**Solution**: Request new certificate with correct key_type

---

## Docker Issues

### Container Keeps Restarting

**Check logs**:
```bash
docker compose logs --tail=50 cert-manager
docker inspect cert-manager | grep -A10 State
```

**Common causes**:
1. Configuration errors
2. Permission issues
3. Port conflicts
4. Resource limits

### Volume Mount Issues

**Symptoms**: Data not persisting, permission errors

**Check mounts**:
```bash
docker inspect cert-manager | grep -A20 Mounts
```

**Verify directories exist**:
```bash
ls -la data/ ssl/
```

### Docker Socket Access

**Symptoms**: Can't reload nginx, "Permission denied" for docker.sock

**Check socket permissions**:
```bash
ls -la /var/run/docker.sock
```

**Solutions**:
```yaml
# Option 1: Add to docker group (in docker-compose.yml)
group_add:
  - "docker"  # or numeric GID

# Option 2: Mount with correct permissions
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

### Out of Disk Space

**Symptoms**: Write errors, container crashes

**Check space**:
```bash
df -h
docker system df
```

**Clean up**:
```bash
docker system prune -a
# Clean old backups
ls -t data/backups/ | tail -n +21 | xargs rm -f
```

---

## Log Analysis

### Important Log Patterns

**Success patterns**:
```
Certificate obtained and saved
Deployment successful
Health check passed
Renewal completed
```

**Warning patterns**:
```
Certificate expiring soon
Retrying request
Rate limit warning
```

**Error patterns**:
```
Error obtaining certificate
Authentication failed
Deployment failed
Challenge validation failed
```

### Log Search Commands

```bash
# Find all errors
grep -i error data/logs/cert-manager.log

# Find ACME issues
grep -i "acme\|certbot\|letsencrypt" data/logs/cert-manager.log

# Find ClearPass issues
grep -i clearpass data/logs/cert-manager.log

# Find recent errors (last 100 lines)
tail -100 data/logs/cert-manager.log | grep -i error

# Follow log in real-time
tail -f data/logs/cert-manager.log
```

### Certbot Logs

```bash
# Main certbot log
cat ssl/logs/letsencrypt.log

# Renewal logs
ls -la ssl/renewal/
```

---

## Getting Help

### Information to Collect

When reporting issues, include:

1. **Application version**: Check Dockerfile or pyproject.toml
2. **Health check output**: `curl localhost:8000/api/health`
3. **Relevant logs**: Last 50-100 lines with errors
4. **Configuration** (sanitized): Remove credentials!
5. **Environment**: Docker version, OS, etc.

### Debug Mode

Enable maximum logging:
```bash
LOG_LEVEL=DEBUG docker compose up 2>&1 | tee debug.log
```

### Test Commands

```bash
# Test ACME credentials
curl http://localhost:8000/api/credentials/acme

# Test ClearPass credentials
curl http://localhost:8000/api/credentials/clearpass

# Test certificate request (dry-run)
# Add --dry-run to certbot command in acme/manager.py

# Test deployment
curl http://localhost:8000/api/services/service-name/health
```

### Common Support Questions

**Q: Why isn't my certificate renewing?**
A: Check: scheduler running, auto_renew enabled, cert in renewal window (30 days)

**Q: Why can't I deploy to ClearPass?**
A: Check: network access, OAuth credentials, API client permissions

**Q: Why is the challenge failing?**
A: Check: DNS propagation (dns-01), port 80 access (http-01), correct credentials

**Q: Why isn't nginx reloading?**
A: Check: docker socket mounted, correct container name, container running
