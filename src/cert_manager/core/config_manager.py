"""YAML configuration management for cert-manager."""

import datetime
import glob as glob_module
import logging
import os
import re
import shutil

import yaml

logger = logging.getLogger("cert_manager.config")


def _sanitize_name(name: str) -> str:
    """Sanitizes a service/pack name to filesystem-safe characters."""
    sanitized = re.sub(r"[^\w\-.]", "_", name.strip())
    if not sanitized:
        raise ValueError("Invalid name provided")
    return sanitized


class ConfigManager:
    """Manages application configuration in a plain YAML file."""

    def __init__(self, config_path: str, backup_dir: str | None = None) -> None:
        self.config_path = config_path
        self.backup_dir = backup_dir
        self.config: dict = {}
        self.load_config()

    def _default_config(self) -> dict:
        return {
            "app": {
                "log_level": "INFO",
                "scheduler_time": "00:30",
            },
            "services": [],
            "service_types": {"clearpass": "clearpass"},
            "cert_packs": {},
            "credentials": {
                "acme": {},
                "clearpass": {},
            },
        }

    def load_config(self) -> dict:
        """Loads plain YAML config. Creates default if missing."""
        if not os.path.exists(self.config_path):
            self.config = self._default_config()
            self.save_config()
            logger.info("Created default configuration file.")
            return self.config

        try:
            with open(self.config_path, "r") as f:
                self.config = yaml.safe_load(f) or self._default_config()
            # Ensure credentials section exists for backwards compatibility
            if "credentials" not in self.config:
                self.config["credentials"] = {"acme": {}, "clearpass": {}}
            logger.info("Configuration loaded.")
            return self.config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            raise

    def save_config(self) -> None:
        """Saves config as plain YAML with backup rotation."""
        self._create_backup()
        os.makedirs(os.path.dirname(os.path.abspath(self.config_path)), exist_ok=True)
        with open(self.config_path, "w") as f:
            yaml.dump(self.config, f, sort_keys=False, default_flow_style=False)

    def _create_backup(self) -> None:
        """Creates a timestamped backup with rotation (keep 20)."""
        if not os.path.exists(self.config_path):
            return

        backup_dir = self.backup_dir or os.path.join(
            os.path.dirname(os.path.abspath(self.config_path)), "backups", "config"
        )
        os.makedirs(backup_dir, exist_ok=True)

        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = os.path.join(backup_dir, f"config.{timestamp}.yaml.bak")
            shutil.copy2(self.config_path, backup_path)

            backups = sorted(glob_module.glob(os.path.join(backup_dir, "config.*.yaml.bak")))
            for old in backups[:-20]:
                try:
                    os.remove(old)
                except Exception as e:
                    logger.warning(f"Failed to delete old backup {old}: {e}")
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")

    # --- App Settings ---

    def get_app_settings(self) -> dict:
        """Returns the app settings section."""
        return self.config.get("app", {})

    def update_app_settings(self, settings: dict) -> None:
        """Updates the app settings section."""
        if "app" not in self.config:
            self.config["app"] = {}
        self.config["app"].update(settings)
        self.save_config()

    # --- Services ---

    def get_services(self) -> list[dict]:
        """Returns the list of managed services."""
        return self.config.get("services", [])

    def get_service(self, name: str) -> dict | None:
        """Returns a single service by name."""
        return next((s for s in self.get_services() if s.get("name") == name), None)

    def validate_service_data(self, data: dict) -> dict:
        """Validates service configuration (non-secret fields only)."""
        for field in ("name", "host", "type"):
            if not data.get(field):
                raise ValueError(f"Missing required field: {field}")
        data["name"] = _sanitize_name(data["name"])
        return data

    def add_service(self, service_data: dict) -> dict:
        """Adds a new service to the configuration."""
        service_data = self.validate_service_data(service_data)
        services = self.get_services()
        if any(s.get("name") == service_data["name"] for s in services):
            raise ValueError("Service name already exists")
        services.append(service_data)
        self.config["services"] = services
        self.save_config()
        return service_data

    def update_service(self, name: str, new_data: dict) -> dict:
        """Updates an existing service's configuration."""
        services = self.get_services()
        for i, s in enumerate(services):
            if s.get("name") == name:
                services[i].update(new_data)
                self.config["services"] = services
                self.save_config()
                return services[i]
        raise ValueError("Service not found")

    def delete_service(self, name: str) -> bool:
        """Removes a service from the configuration."""
        services = self.get_services()
        filtered = [s for s in services if s.get("name") != name]
        if len(filtered) == len(services):
            raise ValueError("Service not found")
        self.config["services"] = filtered
        self.save_config()
        return True

    # --- Cert Pack Metadata ---

    def get_cert_packs_meta(self) -> dict:
        """Returns all cert pack metadata."""
        return self.config.get("cert_packs", {})

    def get_cert_pack_meta(self, pack_id: str) -> dict:
        """Returns metadata for a specific cert pack."""
        return self.config.get("cert_packs", {}).get(pack_id, {})

    def set_cert_pack_meta(self, pack_id: str, meta: dict) -> None:
        """Sets or updates metadata for a cert pack."""
        if "cert_packs" not in self.config:
            self.config["cert_packs"] = {}
        self.config["cert_packs"][pack_id] = meta
        self.save_config()

    def delete_cert_pack_meta(self, pack_id: str) -> None:
        """Removes metadata for a cert pack."""
        packs = self.config.get("cert_packs", {})
        if pack_id in packs:
            del packs[pack_id]
            self.config["cert_packs"] = packs
            self.save_config()

    # --- Credentials (built-in) ---

    def get_acme_credentials(self) -> dict:
        """Returns all ACME credentials."""
        return self.config.get("credentials", {}).get("acme", {})

    def get_acme_credential(self, credential_id: str) -> dict | None:
        """Returns a specific ACME credential by ID."""
        return self.get_acme_credentials().get(credential_id)

    def set_acme_credential(self, credential_id: str, data: dict) -> None:
        """Sets or updates an ACME credential."""
        if "credentials" not in self.config:
            self.config["credentials"] = {"acme": {}, "clearpass": {}}
        if "acme" not in self.config["credentials"]:
            self.config["credentials"]["acme"] = {}
        self.config["credentials"]["acme"][credential_id] = data
        self.save_config()

    def delete_acme_credential(self, credential_id: str) -> bool:
        """Removes an ACME credential."""
        creds = self.config.get("credentials", {}).get("acme", {})
        if credential_id in creds:
            del creds[credential_id]
            self.save_config()
            return True
        return False

    def get_clearpass_credentials(self) -> dict:
        """Returns all ClearPass credentials."""
        return self.config.get("credentials", {}).get("clearpass", {})

    def get_clearpass_credential(self, credential_id: str) -> dict | None:
        """Returns a specific ClearPass credential by ID."""
        return self.get_clearpass_credentials().get(credential_id)

    def set_clearpass_credential(self, credential_id: str, data: dict) -> None:
        """Sets or updates a ClearPass credential."""
        if "credentials" not in self.config:
            self.config["credentials"] = {"acme": {}, "clearpass": {}}
        if "clearpass" not in self.config["credentials"]:
            self.config["credentials"]["clearpass"] = {}
        self.config["credentials"]["clearpass"][credential_id] = data
        self.save_config()

    def delete_clearpass_credential(self, credential_id: str) -> bool:
        """Removes a ClearPass credential."""
        creds = self.config.get("credentials", {}).get("clearpass", {})
        if credential_id in creds:
            del creds[credential_id]
            self.save_config()
            return True
        return False
