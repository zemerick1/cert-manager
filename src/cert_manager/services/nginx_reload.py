"""Nginx reload via Docker socket SIGHUP."""

import logging

logger = logging.getLogger("cert_manager.nginx_reload")

DOCKER_SOCKET = "/var/run/docker.sock"
NGINX_CONTAINER_NAME = "nginx"


async def reload_nginx(container_name: str = NGINX_CONTAINER_NAME) -> bool:
    """Sends SIGHUP to the nginx container to reload its configuration.

    Args:
        container_name: Docker container name for nginx.

    Returns:
        True if signal was sent successfully.
    """
    import asyncio

    try:
        result = await asyncio.to_thread(_send_sighup, container_name)
        return result
    except Exception as e:
        logger.error(f"Failed to reload nginx: {e}")
        return False


def _send_sighup(container_name: str) -> bool:
    """Sends SIGHUP to nginx container via Docker socket HTTP API."""
    try:
        import requests_unixsocket

        session = requests_unixsocket.Session()
        url = (
            f"http+unix://%2Fvar%2Frun%2Fdocker.sock/containers/{container_name}/kill?signal=SIGHUP"
        )

        response = session.post(url)
        if response.status_code == 204:
            logger.info(f"Sent SIGHUP to {container_name} - nginx reloading.")
            return True
        else:
            logger.error(f"Docker API returned {response.status_code}: {response.text}")
            return False
    except ImportError:
        logger.warning("requests-unixsocket not installed, skipping nginx reload")
        return False
    except Exception as e:
        logger.error(f"Docker socket request failed: {e}")
        return False
