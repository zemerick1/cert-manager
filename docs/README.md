# Certificate Manager Documentation

Welcome to the Certificate Manager documentation. This guide covers everything you need to deploy, configure, and maintain the Certificate Manager application.

---

## Quick Links

| Document | Description |
|----------|-------------|
| [Architecture](ARCHITECTURE.md) | System design, components, and data flow |
| [API Reference](API_REFERENCE.md) | Complete REST API documentation |
| [Deployment](DEPLOYMENT.md) | Installation and deployment guides |
| [Configuration](CONFIGURATION.md) | Configuration options reference |
| [ClearPass Integration](CLEARPASS_INTEGRATION.md) | HPE Aruba ClearPass setup guide |
| [Troubleshooting](TROUBLESHOOTING.md) | Common issues and solutions |
| [Development](DEVELOPMENT.md) | Developer guide and contribution |

---

## Getting Started

### New Users

1. **[Deployment Guide](DEPLOYMENT.md)** - Set up Certificate Manager using Docker Compose
2. **[Configuration Reference](CONFIGURATION.md)** - Configure environment and credentials
3. **[API Reference](API_REFERENCE.md)** - Learn the REST API endpoints

### ClearPass Administrators

1. **[ClearPass Integration](CLEARPASS_INTEGRATION.md)** - Complete ClearPass setup
2. **[Configuration Reference](CONFIGURATION.md)** - Service and credential setup
3. **[Troubleshooting](TROUBLESHOOTING.md)** - Resolve deployment issues

### Developers

1. **[Architecture](ARCHITECTURE.md)** - Understand system design
2. **[Development Guide](DEVELOPMENT.md)** - Set up development environment
3. **[API Reference](API_REFERENCE.md)** - API endpoint details

---

## Overview

Certificate Manager is a standalone application for automated SSL/TLS certificate lifecycle management. It integrates with:

- **Let's Encrypt** via ACME protocol for free, automated certificates
- **DNS Providers** (Cloudflare, Route53, DigitalOcean, etc.) for DNS-01 challenges
- **HPE Aruba ClearPass** for automated certificate deployment
- **Nginx** for automatic reload on certificate renewal

### Key Features

- REST API for all operations
- Automatic certificate renewal
- Multi-domain and wildcard certificates
- ClearPass cluster support
- Background health monitoring
- Configuration backup and recovery

---

## Support

For issues and questions:

1. Check the [Troubleshooting Guide](TROUBLESHOOTING.md)
2. Review application logs: `docker compose logs cert-manager`
3. Enable debug logging: `LOG_LEVEL=DEBUG`
4. Open an issue on GitHub

---

## License

MIT License - See LICENSE file for details.
