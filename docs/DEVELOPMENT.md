# Development Guide

Guide for developing and contributing to Certificate Manager.

---

## Table of Contents

1. [Development Setup](#development-setup)
2. [Project Structure](#project-structure)
3. [Code Style](#code-style)
4. [Testing](#testing)
5. [Adding Features](#adding-features)
6. [Adding Providers](#adding-providers)
7. [Adding Handlers](#adding-handlers)
8. [API Development](#api-development)
9. [Building and Releasing](#building-and-releasing)

---

## Development Setup

### Prerequisites

- Python 3.11 or later
- Docker and Docker Compose (for container testing)
- Git

### Local Setup

```bash
# Clone repository
git clone https://github.com/your-org/cert-manager.git
cd cert-manager

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or
.\venv\Scripts\activate   # Windows

# Install in development mode
pip install -e ".[dev]"

# Create data directories
mkdir -p data ssl
touch data/.gitkeep ssl/.gitkeep

# Create environment file
cp .env.example .env
```

### Running Locally

```bash
# Run with hot reload
uvicorn cert_manager.app:app --reload --host 0.0.0.0 --port 8000

# Run with debug logging
LOG_LEVEL=DEBUG uvicorn cert_manager.app:app --reload
```

### Running with Docker

```bash
# Build image
docker build -t cert-manager:dev .

# Run container
docker compose up --build

# Run with rebuild
docker compose up --build --force-recreate
```

---

## Project Structure

```
cert-manager/
├── src/
│   └── cert_manager/
│       ├── __init__.py
│       ├── app.py              # FastAPI application entry point
│       ├── api/
│       │   ├── __init__.py
│       │   ├── routes.py       # API endpoints
│       │   └── models.py       # Pydantic models
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config_manager.py   # Configuration management
│       │   ├── cert_store.py       # Certificate storage
│       │   ├── cert_validator.py   # Certificate validation
│       │   └── crypto_utils.py     # Cryptography utilities
│       ├── acme/
│       │   ├── __init__.py
│       │   └── manager.py      # ACME/Certbot manager
│       ├── handlers/
│       │   ├── __init__.py
│       │   ├── base.py         # Base handler interface
│       │   ├── clearpass.py    # ClearPass handler
│       │   └── clearpass_ca_trust.py  # CA trust management
│       └── services/
│           ├── __init__.py
│           ├── scheduler.py    # Background scheduler
│           └── nginx_reload.py # Nginx reload service
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_acme.py
│   ├── test_config.py
│   └── test_handlers.py
├── docs/
│   ├── API_REFERENCE.md
│   ├── ARCHITECTURE.md
│   ├── CLEARPASS_INTEGRATION.md
│   ├── CONFIGURATION.md
│   ├── DEPLOYMENT.md
│   ├── DEVELOPMENT.md
│   └── TROUBLESHOOTING.md
├── data/                   # Runtime data (gitignored)
├── ssl/                    # Certificates (gitignored)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

### Key Modules

| Module | Purpose |
|--------|---------|
| `app.py` | FastAPI app initialization, lifespan management |
| `api/routes.py` | REST API endpoint definitions |
| `api/models.py` | Request/response Pydantic models |
| `core/config_manager.py` | YAML config loading, saving, backup |
| `core/cert_store.py` | Certificate file operations |
| `core/cert_validator.py` | X.509 certificate parsing |
| `core/crypto_utils.py` | PFX generation, key operations |
| `acme/manager.py` | Certbot CLI wrapper |
| `handlers/clearpass.py` | ClearPass API integration |
| `services/scheduler.py` | Background task scheduler |

---

## Code Style

### Python Style

Follow PEP 8 with these specifics:

- Line length: 100 characters
- Use type hints for function signatures
- Use docstrings for public functions
- Prefer f-strings for formatting

### Example

```python
from typing import Optional, List
from datetime import datetime

def get_certificate_info(
    cert_path: str,
    include_chain: bool = False
) -> Optional[dict]:
    """
    Extract information from a certificate file.

    Args:
        cert_path: Path to the PEM certificate file
        include_chain: Whether to include chain certificates

    Returns:
        Dictionary with certificate info or None if invalid
    """
    # Implementation
    pass
```

### Imports

Order imports:
1. Standard library
2. Third-party packages
3. Local modules

```python
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cert_manager.core.config_manager import ConfigManager
from cert_manager.core.cert_store import CertStore
```

### Logging

Use structured logging:

```python
import logging

logger = logging.getLogger(__name__)

# Good
logger.info("Certificate renewed", extra={
    "pack_name": pack_name,
    "days_remaining": days
})

# Also good
logger.info(f"Certificate '{pack_name}' renewed, {days} days remaining")

# Avoid
print(f"Certificate renewed: {pack_name}")
```

---

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=cert_manager --cov-report=html

# Run specific test file
pytest tests/test_api.py

# Run specific test
pytest tests/test_api.py::test_health_endpoint

# Run with verbose output
pytest -v
```

### Test Structure

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from cert_manager.app import app

@pytest.fixture
def client():
    """Test client fixture"""
    with TestClient(app) as client:
        yield client

@pytest.fixture
def sample_config():
    """Sample configuration for testing"""
    return {
        "settings": {"log_level": "INFO"},
        "cert_packs": {},
        "services": {},
        "acme_credentials": {},
        "clearpass_credentials": {}
    }
```

```python
# tests/test_api.py
def test_health_endpoint(client):
    """Test health check returns correct structure"""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"

def test_list_certs_empty(client):
    """Test listing certificates when none exist"""
    response = client.get("/api/certs")
    assert response.status_code == 200
    assert response.json() == []
```

### Mocking External Services

```python
from unittest.mock import Mock, patch

def test_acme_request_with_mock():
    """Test ACME request without calling real Certbot"""
    with patch("cert_manager.acme.manager.subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        # Test code that calls Certbot
        result = acme_manager.request_certificate(...)

        # Verify Certbot was called correctly
        mock_run.assert_called_once()
        assert "certbot" in mock_run.call_args[0][0][0]
```

---

## Adding Features

### Feature Development Workflow

1. **Create branch**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Implement feature**
   - Add/modify code
   - Add tests
   - Update documentation

3. **Test locally**
   ```bash
   pytest
   uvicorn cert_manager.app:app --reload
   ```

4. **Submit PR**
   ```bash
   git add .
   git commit -m "Add feature: description"
   git push origin feature/my-feature
   ```

### Adding a New API Endpoint

1. **Add Pydantic model** (api/models.py):
   ```python
   class NewFeatureRequest(BaseModel):
       name: str
       option: Optional[str] = None

   class NewFeatureResponse(BaseModel):
       success: bool
       data: dict
   ```

2. **Add route** (api/routes.py):
   ```python
   @router.post("/api/new-feature", response_model=NewFeatureResponse)
   async def new_feature(
       request: NewFeatureRequest,
       context: AppContext = Depends(get_context)
   ):
       """New feature endpoint"""
       # Implementation
       return NewFeatureResponse(success=True, data={})
   ```

3. **Add tests** (tests/test_api.py):
   ```python
   def test_new_feature(client):
       response = client.post("/api/new-feature", json={"name": "test"})
       assert response.status_code == 200
   ```

4. **Update documentation** (docs/API_REFERENCE.md)

---

## Adding Providers

### ACME DNS Providers

To add a new DNS provider for ACME challenges:

1. **Add to provider enum** (api/models.py):
   ```python
   class AcmeProvider(str, Enum):
       CLOUDFLARE = "cloudflare"
       # ...
       NEW_PROVIDER = "new_provider"  # Add here
   ```

2. **Add credential fields** (core/config_manager.py):
   ```python
   # In the schema or validation
   NEW_PROVIDER_FIELDS = ["api_key", "api_secret"]
   ```

3. **Add Certbot integration** (acme/manager.py):
   ```python
   def _get_provider_env(self, provider: str, credential: dict) -> dict:
       """Get environment variables for DNS provider"""
       if provider == "new_provider":
           return {
               "NEW_PROVIDER_API_KEY": credential["api_key"],
               "NEW_PROVIDER_API_SECRET": credential["api_secret"]
           }
       # ... existing providers

   def _get_certbot_plugin(self, provider: str) -> str:
       """Get Certbot plugin name for provider"""
       plugins = {
           "new_provider": "dns-new-provider",
           # ... existing providers
       }
       return plugins.get(provider, f"dns-{provider}")
   ```

4. **Install Certbot plugin** (Dockerfile):
   ```dockerfile
   RUN pip install certbot-dns-new-provider
   ```

5. **Add documentation** (docs/CONFIGURATION.md)

### ACME HTTP Providers

Similar process for HTTP-01 challenge providers (webroot, standalone, etc.):

```python
# In acme/manager.py
def _build_http_certbot_command(self, provider: str, ...):
    if provider == "new_http_provider":
        return [
            "certbot", "certonly",
            "--new-http-provider",
            "--webroot-path", webroot_path,
            # ...
        ]
```

---

## Adding Handlers

### Handler Interface

All service handlers inherit from the base handler:

```python
# handlers/base.py
from abc import ABC, abstractmethod
from typing import Optional

class ServiceHandler(ABC):
    """Base class for service handlers"""

    @abstractmethod
    def deploy_certificate(
        self,
        service: dict,
        cert_pack: dict,
        fullchain: str,
        privkey: str
    ) -> bool:
        """Deploy certificate to service"""
        pass

    @abstractmethod
    def check_health(self, service: dict) -> dict:
        """Check service health and certificate status"""
        pass
```

### Creating a New Handler

1. **Create handler file** (handlers/new_service.py):
   ```python
   import logging
   from typing import Optional
   from .base import ServiceHandler

   logger = logging.getLogger(__name__)

   class NewServiceHandler(ServiceHandler):
       """Handler for NewService certificate deployment"""

       def __init__(self, config_manager):
           self.config = config_manager

       def deploy_certificate(
           self,
           service: dict,
           cert_pack: dict,
           fullchain: str,
           privkey: str
       ) -> bool:
           """Deploy certificate to NewService"""
           try:
               # Get credentials
               cred = self.config.get_newservice_credential(
                   service["credential_id"]
               )
               if not cred:
                   logger.error("Credential not found")
                   return False

               # Implementation
               # ...

               return True
           except Exception as e:
               logger.error(f"Deployment failed: {e}")
               return False

       def check_health(self, service: dict) -> dict:
           """Check certificate status on NewService"""
           try:
               # Implementation
               return {
                   "success": True,
                   "expiry": "2024-04-01",
                   "days_remaining": 90
               }
           except Exception as e:
               return {
                   "success": False,
                   "error": str(e)
               }
   ```

2. **Register handler** (handlers/__init__.py):
   ```python
   from .clearpass import ClearPassHandler
   from .new_service import NewServiceHandler

   HANDLERS = {
       "clearpass": ClearPassHandler,
       "new_service": NewServiceHandler,
   }

   def get_handler(service_type: str, config_manager):
       """Get handler for service type"""
       handler_class = HANDLERS.get(service_type)
       if handler_class:
           return handler_class(config_manager)
       return None
   ```

3. **Add service type** (api/models.py):
   ```python
   class ServiceType(str, Enum):
       CLEARPASS = "clearpass"
       NEW_SERVICE = "new_service"
   ```

4. **Add credential type** if needed (config_manager.py)

5. **Add tests and documentation**

---

## API Development

### FastAPI Patterns

**Dependency injection**:
```python
from fastapi import Depends

def get_context() -> AppContext:
    """Get application context"""
    return app.state.context

@router.get("/api/endpoint")
async def endpoint(context: AppContext = Depends(get_context)):
    # Use context.config, context.cert_store, etc.
    pass
```

**Error handling**:
```python
from fastapi import HTTPException

@router.get("/api/certs/{pack_name}")
async def get_cert(pack_name: str, context: AppContext = Depends(get_context)):
    pack = context.config.get_cert_pack(pack_name)
    if not pack:
        raise HTTPException(status_code=404, detail="Certificate pack not found")
    return pack
```

**Response models**:
```python
from pydantic import BaseModel
from typing import Optional, Any

class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None

@router.post("/api/action", response_model=ApiResponse)
async def action():
    return ApiResponse(
        success=True,
        message="Action completed",
        data={"result": "value"}
    )
```

### OpenAPI Documentation

FastAPI auto-generates OpenAPI docs. Enhance with:

```python
@router.post(
    "/api/certs/request",
    response_model=ApiResponse,
    summary="Request ACME Certificate",
    description="Request a new certificate from Let's Encrypt using ACME protocol",
    responses={
        200: {"description": "Certificate requested successfully"},
        400: {"description": "Invalid request parameters"},
        500: {"description": "ACME request failed"}
    }
)
async def request_cert(request: CertRequest):
    """
    Request a new ACME certificate.

    - **pack_name**: Unique name for the certificate pack
    - **domains**: List of domains to include
    - **provider**: DNS provider for challenge
    """
    pass
```

---

## Building and Releasing

### Version Management

Update version in `pyproject.toml`:
```toml
[project]
name = "cert-manager"
version = "1.1.0"
```

### Building Docker Image

```bash
# Build with tag
docker build -t cert-manager:1.1.0 .
docker build -t cert-manager:latest .

# Multi-platform build
docker buildx build --platform linux/amd64,linux/arm64 -t cert-manager:1.1.0 .
```

### Release Checklist

1. [ ] Update version in pyproject.toml
2. [ ] Update CHANGELOG.md
3. [ ] Run full test suite
4. [ ] Build and test Docker image
5. [ ] Tag release in git
6. [ ] Push to registry
7. [ ] Update documentation

### Changelog Format

```markdown
## [1.1.0] - 2024-01-15

### Added
- New feature description

### Changed
- Changed behavior description

### Fixed
- Bug fix description

### Security
- Security fix description
```

---

## Debugging Tips

### VS Code Launch Config

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": ["cert_manager.app:app", "--reload"],
      "env": {
        "LOG_LEVEL": "DEBUG"
      }
    }
  ]
}
```

### Interactive Testing

```python
# Start Python REPL
python

>>> from cert_manager.core.config_manager import ConfigManager
>>> config = ConfigManager("/path/to/data")
>>> config.get_all_cert_packs()
```

### Request Debugging

```bash
# Verbose curl
curl -v http://localhost:8000/api/health

# With headers
curl -i http://localhost:8000/api/certs

# POST with data
curl -X POST http://localhost:8000/api/certs/request \
  -H "Content-Type: application/json" \
  -d '{"pack_name": "test", "domains": ["example.com"]}' \
  -v
```
