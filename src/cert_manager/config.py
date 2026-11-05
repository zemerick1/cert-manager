"""Application configuration using Pydantic Settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Paths
    data_dir: str = "/app/data"
    ssl_dir: str = "/etc/letsencrypt"

    # Domain configuration
    edge_domain: str = ""

    # Logging
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Login for the setup page, API docs, and /api. Empty password leaves them open.
    admin_username: str = "admin"
    admin_password: str = ""

    # Docker socket for nginx reload (optional)
    docker_socket: str = "/var/run/docker.sock"
    nginx_container_name: str = "nginx"

    # Scheduler
    scheduler_enabled: bool = True
    scheduler_time: str = "00:30"  # Daily renewal check time (UTC)
    service_check_interval: int = 300  # Health check interval in seconds

    class Config:
        env_prefix = ""
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    """Returns cached settings instance."""
    return Settings()
