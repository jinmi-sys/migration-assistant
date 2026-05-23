"""Encryption utilities for credential transfer."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def generate_key(passphrase: str = "", salt: bytes = b"") -> tuple[bytes, bytes]:
    """Generate Fernet key from passphrase. Returns (key, salt)."""
    if not salt:
        salt = os.urandom(16)
    if not passphrase:
        return Fernet.generate_key(), salt

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return key, salt


def encrypt_file(input_path: str, output_path: str, key: bytes) -> int:
    """Encrypt file. Returns bytes written."""
    fernet = Fernet(key)
    data = Path(input_path).read_bytes()
    encrypted = fernet.encrypt(data)
    Path(output_path).write_bytes(encrypted)
    return len(encrypted)


def decrypt_file(input_path: str, output_path: str, key: bytes) -> int:
    """Decrypt file. Returns bytes written."""
    fernet = Fernet(key)
    data = Path(input_path).read_bytes()
    decrypted = fernet.decrypt(data)
    Path(output_path).write_bytes(decrypted)
    return len(decrypted)


def encrypt_string(content: str, key: bytes) -> bytes:
    """Encrypt string content. Returns encrypted bytes."""
    return Fernet(key).encrypt(content.encode())


def decrypt_string(encrypted: bytes, key: bytes) -> str:
    """Decrypt bytes to string."""
    return Fernet(key).decrypt(encrypted).decode()
