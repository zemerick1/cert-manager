"""Fernet encryption utilities for secrets at rest."""

import base64
import json
import logging
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger("cert_manager.crypto")

MAGIC_HEADER = b"ENC:"
SALT_LENGTH = 16
PBKDF2_ITERATIONS = 100_000


def derive_key(password: str, salt: bytes) -> bytes:
    """Derives a Fernet-compatible key from a password and salt.

    Args:
        password: Master password string.
        salt: 16-byte random salt.

    Returns:
        Base64-encoded 32-byte Fernet key.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt_data(data: dict, password: str) -> bytes:
    """Encrypts a dictionary using password-derived Fernet key.

    Args:
        data: Dictionary to encrypt.
        password: Master password.

    Returns:
        Bytes in format: ENC:[16-byte salt][encrypted payload].
    """
    salt = os.urandom(SALT_LENGTH)
    key = derive_key(password, salt)
    fernet = Fernet(key)
    payload = fernet.encrypt(json.dumps(data).encode())
    return MAGIC_HEADER + salt + payload


def decrypt_data(file_content: bytes, password: str) -> dict:
    """Decrypts bytes back into a dictionary using password.

    Args:
        file_content: Encrypted bytes starting with ENC: header.
        password: Master password.

    Returns:
        Decrypted dictionary.

    Raises:
        ValueError: If file format is invalid.
    """
    if not file_content.startswith(MAGIC_HEADER):
        raise ValueError("Invalid file format (missing magic header)")

    header_len = len(MAGIC_HEADER)
    salt = file_content[header_len : header_len + SALT_LENGTH]
    encrypted_payload = file_content[header_len + SALT_LENGTH :]

    key = derive_key(password, salt)
    fernet = Fernet(key)
    decrypted = fernet.decrypt(encrypted_payload)
    return json.loads(decrypted.decode())


def generate_keyfile(keyfile_path: str) -> bytes:
    """Generates a random keyfile for auto-unsealing.

    Args:
        keyfile_path: Path to write the keyfile.

    Returns:
        The generated key bytes.
    """
    key = Fernet.generate_key()
    os.makedirs(os.path.dirname(keyfile_path), exist_ok=True)
    with open(keyfile_path, "wb") as f:
        f.write(key)
    os.chmod(keyfile_path, 0o600)
    logger.info(f"Generated new keyfile at {keyfile_path}")
    return key


def load_or_create_keyfile(keyfile_path: str) -> bytes:
    """Loads an existing keyfile or creates a new one.

    Args:
        keyfile_path: Path to the keyfile.

    Returns:
        The Fernet key bytes.
    """
    if os.path.exists(keyfile_path):
        with open(keyfile_path, "rb") as f:
            return f.read()
    return generate_keyfile(keyfile_path)


def encrypt_with_keyfile(data: dict, key: bytes) -> bytes:
    """Encrypts data using a pre-derived Fernet key.

    Args:
        data: Dictionary to encrypt.
        key: Fernet key bytes.

    Returns:
        Encrypted bytes with magic header.
    """
    fernet = Fernet(key)
    payload = fernet.encrypt(json.dumps(data).encode())
    # Use empty salt placeholder for format compatibility
    return MAGIC_HEADER + (b"\x00" * SALT_LENGTH) + payload


def decrypt_with_keyfile(file_content: bytes, key: bytes) -> dict:
    """Decrypts data using a pre-derived Fernet key.

    Args:
        file_content: Encrypted bytes with magic header.
        key: Fernet key bytes.

    Returns:
        Decrypted dictionary.
    """
    if not file_content.startswith(MAGIC_HEADER):
        raise ValueError("Invalid file format (missing magic header)")

    header_len = len(MAGIC_HEADER)
    encrypted_payload = file_content[header_len + SALT_LENGTH :]
    fernet = Fernet(key)
    decrypted = fernet.decrypt(encrypted_payload)
    return json.loads(decrypted.decode())


def is_encrypted(file_path: str) -> bool:
    """Checks if a file has the ENC: magic header."""
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, "rb") as f:
            return f.read(len(MAGIC_HEADER)) == MAGIC_HEADER
    except Exception:
        return False
