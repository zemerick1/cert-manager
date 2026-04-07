"""Tests for Fernet encryption utilities."""

import os

from cert_manager.core.crypto_utils import (
    decrypt_data,
    decrypt_with_keyfile,
    encrypt_data,
    encrypt_with_keyfile,
    generate_keyfile,
    is_encrypted,
    load_or_create_keyfile,
)


class TestPasswordEncryption:
    def test_round_trip(self):
        data = {"secret": "value", "count": 42}
        password = "test-password-123"
        encrypted = encrypt_data(data, password)
        decrypted = decrypt_data(encrypted, password)
        assert decrypted == data

    def test_magic_header(self):
        encrypted = encrypt_data({"a": 1}, "pw")
        assert encrypted.startswith(b"ENC:")

    def test_wrong_password_raises(self):
        encrypted = encrypt_data({"a": 1}, "correct")
        try:
            decrypt_data(encrypted, "wrong")
            assert False, "Should have raised"
        except Exception:
            pass

    def test_invalid_format_raises(self):
        try:
            decrypt_data(b"not encrypted", "pw")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestKeyfileEncryption:
    def test_round_trip(self, tmp_path):
        keyfile = str(tmp_path / "test.key")
        key = generate_keyfile(keyfile)
        data = {"secret": "keyfile-value"}
        encrypted = encrypt_with_keyfile(data, key)
        decrypted = decrypt_with_keyfile(encrypted, key)
        assert decrypted == data

    def test_generate_keyfile_permissions(self, tmp_path):
        keyfile = str(tmp_path / "perm.key")
        generate_keyfile(keyfile)
        mode = os.stat(keyfile).st_mode & 0o777
        assert mode == 0o600

    def test_load_or_create_new(self, tmp_path):
        keyfile = str(tmp_path / "new.key")
        key = load_or_create_keyfile(keyfile)
        assert os.path.exists(keyfile)
        assert len(key) > 0

    def test_load_or_create_existing(self, tmp_path):
        keyfile = str(tmp_path / "existing.key")
        key1 = load_or_create_keyfile(keyfile)
        key2 = load_or_create_keyfile(keyfile)
        assert key1 == key2


class TestIsEncrypted:
    def test_encrypted_file(self, tmp_path):
        f = tmp_path / "enc.dat"
        f.write_bytes(encrypt_data({"a": 1}, "pw"))
        assert is_encrypted(str(f)) is True

    def test_plain_file(self, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_text("hello")
        assert is_encrypted(str(f)) is False

    def test_missing_file(self):
        assert is_encrypted("/nonexistent/path") is False
