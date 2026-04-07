"""Shared fixtures for cert-manager tests."""

import os

import pytest
from fastapi.testclient import TestClient

from cert_manager.core.config_manager import ConfigManager


@pytest.fixture()
def tmp_data_dir(tmp_path):
    """Provides a temporary data directory with required subdirectories."""
    for sub in ("certs", "logs", "backups"):
        (tmp_path / sub).mkdir()
    return tmp_path


@pytest.fixture()
def config_manager(tmp_data_dir):
    """Provides a ConfigManager backed by a temporary config file."""
    config_path = str(tmp_data_dir / "config.yaml")
    return ConfigManager(config_path, backup_dir=str(tmp_data_dir / "backups"))


@pytest.fixture()
def app_client(tmp_data_dir, monkeypatch):
    """Provides a FastAPI TestClient with isolated data/ssl directories."""
    ssl_dir = str(tmp_data_dir / "ssl")
    os.makedirs(os.path.join(ssl_dir, "live"), exist_ok=True)

    monkeypatch.setenv("DATA_DIR", str(tmp_data_dir))
    monkeypatch.setenv("SSL_DIR", ssl_dir)
    monkeypatch.setenv("EDGE_DOMAIN", "localhost")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    # Clear the cached settings so the monkeypatched env vars take effect.
    from cert_manager.config import get_settings

    get_settings.cache_clear()

    from cert_manager.app import app

    with TestClient(app) as client:
        yield client

    get_settings.cache_clear()
