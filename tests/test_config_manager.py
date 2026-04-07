"""Tests for ConfigManager YAML operations."""

import os

import pytest

from cert_manager.core.config_manager import ConfigManager, _sanitize_name


class TestSanitizeName:
    def test_basic(self):
        assert _sanitize_name("my-service") == "my-service"

    def test_strips_whitespace(self):
        assert _sanitize_name("  test  ") == "test"

    def test_replaces_special_chars(self):
        assert _sanitize_name("my service!@#") == "my_service___"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _sanitize_name("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            _sanitize_name("   ")


class TestConfigManagerInit:
    def test_creates_default_config(self, tmp_data_dir):
        config_path = str(tmp_data_dir / "config.yaml")
        assert not os.path.exists(config_path)
        cm = ConfigManager(config_path)
        assert os.path.exists(config_path)
        assert cm.config.get("services") == []
        assert cm.config.get("cert_packs") == {}

    def test_loads_existing_config(self, tmp_data_dir):
        config_path = str(tmp_data_dir / "config.yaml")
        cm1 = ConfigManager(config_path)
        cm1.set_acme_credential("test-cred", {"name": "Test", "provider": "cloudflare"})
        cm2 = ConfigManager(config_path)
        assert cm2.get_acme_credential("test-cred") is not None


class TestAppSettings:
    def test_get_default(self, config_manager):
        settings = config_manager.get_app_settings()
        assert settings.get("log_level") == "INFO"

    def test_update(self, config_manager):
        config_manager.update_app_settings({"log_level": "DEBUG"})
        assert config_manager.get_app_settings()["log_level"] == "DEBUG"


class TestServices:
    def test_add_and_get(self, config_manager):
        svc = config_manager.add_service(
            {
                "name": "test-svc",
                "host": "host.example.com",
                "type": "clearpass",
            }
        )
        assert svc["name"] == "test-svc"
        assert config_manager.get_service("test-svc") is not None

    def test_add_duplicate_raises(self, config_manager):
        config_manager.add_service(
            {
                "name": "dup",
                "host": "h",
                "type": "clearpass",
            }
        )
        with pytest.raises(ValueError, match="already exists"):
            config_manager.add_service(
                {
                    "name": "dup",
                    "host": "h2",
                    "type": "clearpass",
                }
            )

    def test_update_service(self, config_manager):
        config_manager.add_service(
            {
                "name": "upd",
                "host": "old",
                "type": "clearpass",
            }
        )
        result = config_manager.update_service("upd", {"host": "new"})
        assert result["host"] == "new"

    def test_update_nonexistent_raises(self, config_manager):
        with pytest.raises(ValueError, match="not found"):
            config_manager.update_service("nope", {"host": "x"})

    def test_delete_service(self, config_manager):
        config_manager.add_service(
            {
                "name": "del-me",
                "host": "h",
                "type": "clearpass",
            }
        )
        config_manager.delete_service("del-me")
        assert config_manager.get_service("del-me") is None

    def test_delete_nonexistent_raises(self, config_manager):
        with pytest.raises(ValueError, match="not found"):
            config_manager.delete_service("ghost")

    def test_list_services(self, config_manager):
        assert config_manager.get_services() == []
        config_manager.add_service(
            {
                "name": "a",
                "host": "h",
                "type": "clearpass",
            }
        )
        assert len(config_manager.get_services()) == 1


class TestCertPackMeta:
    def test_set_and_get(self, config_manager):
        config_manager.set_cert_pack_meta("my-cert", {"source": "acme"})
        meta = config_manager.get_cert_pack_meta("my-cert")
        assert meta["source"] == "acme"

    def test_get_nonexistent(self, config_manager):
        assert config_manager.get_cert_pack_meta("nope") == {}

    def test_delete(self, config_manager):
        config_manager.set_cert_pack_meta("rm-cert", {"source": "manual"})
        config_manager.delete_cert_pack_meta("rm-cert")
        assert config_manager.get_cert_pack_meta("rm-cert") == {}

    def test_get_all(self, config_manager):
        config_manager.set_cert_pack_meta("a", {"source": "acme"})
        config_manager.set_cert_pack_meta("b", {"source": "manual"})
        all_meta = config_manager.get_cert_packs_meta()
        assert len(all_meta) == 2


class TestAcmeCredentials:
    def test_set_and_get(self, config_manager):
        config_manager.set_acme_credential("cf", {"name": "CF", "provider": "cloudflare"})
        cred = config_manager.get_acme_credential("cf")
        assert cred["provider"] == "cloudflare"

    def test_get_all(self, config_manager):
        config_manager.set_acme_credential("a", {"name": "A"})
        config_manager.set_acme_credential("b", {"name": "B"})
        assert len(config_manager.get_acme_credentials()) == 2

    def test_delete(self, config_manager):
        config_manager.set_acme_credential("del", {"name": "Del"})
        assert config_manager.delete_acme_credential("del") is True
        assert config_manager.get_acme_credential("del") is None

    def test_delete_nonexistent(self, config_manager):
        assert config_manager.delete_acme_credential("nope") is False


class TestClearPassCredentials:
    def test_set_and_get(self, config_manager):
        config_manager.set_clearpass_credential(
            "cp",
            {
                "name": "CP",
                "host": "cp.example.com",
            },
        )
        cred = config_manager.get_clearpass_credential("cp")
        assert cred["host"] == "cp.example.com"

    def test_delete(self, config_manager):
        config_manager.set_clearpass_credential("rm", {"name": "RM"})
        assert config_manager.delete_clearpass_credential("rm") is True
        assert config_manager.get_clearpass_credential("rm") is None

    def test_delete_nonexistent(self, config_manager):
        assert config_manager.delete_clearpass_credential("nope") is False


class TestBackups:
    def test_backup_created_on_save(self, config_manager, tmp_data_dir):
        config_manager.update_app_settings({"log_level": "WARNING"})
        backups_dir = tmp_data_dir / "backups"
        backup_files = list(backups_dir.rglob("*.yaml.bak"))
        assert len(backup_files) >= 1
