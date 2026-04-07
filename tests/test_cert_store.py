"""Tests for CertStore file operations."""

import os

from cert_manager.core.cert_store import CertStore, _detect_source_from_issuer
from tests.test_cert_validator import _generate_self_signed


class TestDetectSource:
    def test_lets_encrypt(self):
        assert _detect_source_from_issuer("CN=R3,O=Let's Encrypt,C=US") == "acme"

    def test_zerossl(self):
        assert _detect_source_from_issuer("O=ZeroSSL") == "acme"

    def test_unknown_issuer(self):
        assert _detect_source_from_issuer("CN=My CA") == "manual"

    def test_none(self):
        assert _detect_source_from_issuer(None) == "manual"


class TestCertStoreSavePack:
    def test_save_non_edge(self, tmp_path):
        ssl_dir = str(tmp_path / "ssl")
        certs_dir = str(tmp_path / "certs")
        os.makedirs(ssl_dir)
        os.makedirs(certs_dir)
        store = CertStore(ssl_dir=ssl_dir, certs_dir=certs_dir)

        cert_pem, key_pem, _, _ = _generate_self_signed()
        path = store.save_pack("test-pack", cert_pem, key_pem, is_edge=False)
        assert os.path.isfile(os.path.join(path, "fullchain.pem"))
        assert os.path.isfile(os.path.join(path, "privkey.pem"))

    def test_save_edge(self, tmp_path):
        ssl_dir = str(tmp_path / "ssl")
        certs_dir = str(tmp_path / "certs")
        os.makedirs(os.path.join(ssl_dir, "live"), exist_ok=True)
        os.makedirs(certs_dir)
        store = CertStore(ssl_dir=ssl_dir, certs_dir=certs_dir, edge_domain="example.com")

        cert_pem, key_pem, _, _ = _generate_self_signed()
        path = store.save_pack("my-cert", cert_pem, key_pem, is_edge=True)
        assert "ssl" in path
        # Edge domain symlink should be created when pack name != edge_domain
        link_path = os.path.join(ssl_dir, "live", "example.com")
        assert os.path.islink(link_path)


class TestCertStoreGetPackPaths:
    def test_found(self, tmp_path):
        ssl_dir = str(tmp_path / "ssl")
        certs_dir = str(tmp_path / "certs")
        os.makedirs(ssl_dir)
        os.makedirs(certs_dir)
        store = CertStore(ssl_dir=ssl_dir, certs_dir=certs_dir)

        cert_pem, key_pem, _, _ = _generate_self_signed()
        store.save_pack("found-pack", cert_pem, key_pem)

        paths = store.get_pack_paths("found-pack")
        assert paths is not None
        assert paths[0].endswith("fullchain.pem")

    def test_not_found(self, tmp_path):
        ssl_dir = str(tmp_path / "ssl")
        certs_dir = str(tmp_path / "certs")
        os.makedirs(ssl_dir)
        os.makedirs(certs_dir)
        store = CertStore(ssl_dir=ssl_dir, certs_dir=certs_dir)
        assert store.get_pack_paths("ghost") is None


class TestCertStoreDeletePack:
    def test_delete_existing(self, tmp_path):
        ssl_dir = str(tmp_path / "ssl")
        certs_dir = str(tmp_path / "certs")
        os.makedirs(ssl_dir)
        os.makedirs(certs_dir)
        store = CertStore(ssl_dir=ssl_dir, certs_dir=certs_dir)

        cert_pem, key_pem, _, _ = _generate_self_signed()
        store.save_pack("del-pack", cert_pem, key_pem)
        assert store.delete_pack("del-pack") is True
        assert store.get_pack_paths("del-pack") is None

    def test_delete_nonexistent(self, tmp_path):
        ssl_dir = str(tmp_path / "ssl")
        certs_dir = str(tmp_path / "certs")
        os.makedirs(ssl_dir)
        os.makedirs(certs_dir)
        store = CertStore(ssl_dir=ssl_dir, certs_dir=certs_dir)
        assert store.delete_pack("nope") is False


class TestCertStoreListPacks:
    def test_list_with_packs(self, tmp_path):
        ssl_dir = str(tmp_path / "ssl")
        certs_dir = str(tmp_path / "certs")
        os.makedirs(os.path.join(ssl_dir, "live"), exist_ok=True)
        os.makedirs(certs_dir)
        store = CertStore(ssl_dir=ssl_dir, certs_dir=certs_dir)

        cert_pem, key_pem, _, _ = _generate_self_signed(cn="test.com", sans=["test.com"])
        store.save_pack("list-pack", cert_pem, key_pem, is_edge=False)

        packs = store.list_packs()
        assert len(packs) == 1
        assert packs[0]["name"] == "list-pack"

    def test_list_empty(self, tmp_path):
        ssl_dir = str(tmp_path / "ssl")
        certs_dir = str(tmp_path / "certs")
        os.makedirs(ssl_dir)
        os.makedirs(certs_dir)
        store = CertStore(ssl_dir=ssl_dir, certs_dir=certs_dir)
        assert store.list_packs() == []
