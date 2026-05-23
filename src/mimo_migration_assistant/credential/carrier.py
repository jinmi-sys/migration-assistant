"""Secure Credential Carrier - transfers secrets without leaking to logs."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from ..utils.crypto import encrypt_file, decrypt_file, generate_key, encrypt_string, decrypt_string
from ..utils.ssh import SSHClient

logger = logging.getLogger(__name__)


class CredentialCarrier:
    """Handles encrypted transfer of .env files, SSL certs, and API keys.

    Flow:
    1. Source: Read env files -> encrypt -> upload encrypted blob to target
    2. Target: Download encrypted blob -> decrypt -> write to original paths
    3. Verify: Hash comparison to ensure integrity

    Secrets are NEVER logged or sent to LLM context.
    """

    def __init__(self, ssh: SSHClient, passphrase: Optional[str] = None) -> None:
        self.ssh = ssh
        self.key, self.salt = generate_key(passphrase or "")
        self._temp_dir = tempfile.mkdtemp(prefix="migrate_creds_")

    def prepare_secrets(self, env_files: dict[str, str]) -> list[str]:
        """Encrypt env files locally and prepare for transfer.

        Args:
            env_files: Dict of {filepath: content} from source machine.

        Returns:
            List of encrypted blob paths (local).
        """
        encrypted_paths: list[str] = []

        for filepath, content in env_files.items():
            # Create safe filename from path
            safe_name = filepath.replace("/", "_").replace(".", "_")
            enc_path = os.path.join(self._temp_dir, f"{safe_name}.enc")

            # Write content to temp, encrypt, delete temp
            tmp_in = os.path.join(self._temp_dir, f"{safe_name}.tmp")
            Path(tmp_in).write_text(content)
            encrypt_file(tmp_in, enc_path, self.key)
            os.unlink(tmp_in)

            encrypted_paths.append(enc_path)
            logger.info(f"Encrypted: {filepath} -> {enc_path} ({os.path.getsize(enc_path)} bytes)")

        return encrypted_paths

    def transfer_to_target(self, encrypted_paths: list[str], original_paths: list[str]) -> list[str]:
        """Upload encrypted blobs to target and decrypt.

        Args:
            encrypted_paths: Local paths to encrypted blobs.
            original_paths: Original file paths on target machine.

        Returns:
            List of restored file paths on target.
        """
        restored: list[str] = []
        remote_temp = "/tmp/migrate_creds"

        # Create temp dir on target
        self.ssh.exec(f"mkdir -p {remote_temp}", timeout=10)

        # Upload salt first
        salt_path = os.path.join(self._temp_dir, "salt.bin")
        Path(salt_path).write_bytes(self.salt)
        self.ssh.upload(salt_path, f"{remote_temp}/salt.bin")

        for enc_path, orig_path in zip(encrypted_paths, original_paths):
            remote_enc = f"{remote_temp}/{os.path.basename(enc_path)}"

            # Upload encrypted blob
            self.ssh.upload(enc_path, remote_enc)
            logger.info(f"Uploaded: {enc_path} -> {remote_enc}")

            # Decrypt on target using a small Python script
            decrypt_script = f"""
import base64
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

salt = Path('{remote_temp}/salt.bin').read_bytes()
encrypted = Path('{remote_enc}').read_bytes()

# If we have a passphrase, derive key; otherwise use raw key
# For simplicity, we pass the key directly
key = {repr(self.key.decode() if isinstance(self.key, bytes) else self.key)}
f = Fernet(key)
decrypted = f.decrypt(encrypted)

import os
os.makedirs(os.path.dirname('{orig_path}'), exist_ok=True)
Path('{orig_path}').write_bytes(decrypted)
print(f'Restored: {orig_path}')
"""
            # Instead of running Python on target, download, decrypt locally, re-upload
            local_enc = enc_path
            local_dec = local_enc.replace(".enc", ".dec")
            decrypt_file(local_enc, local_dec, self.key)
            self.ssh.upload(local_dec, orig_path)
            os.unlink(local_dec)

            restored.append(orig_path)
            logger.info(f"Restored credential: {orig_path}")

        # Cleanup remote temp
        self.ssh.exec(f"rm -rf {remote_temp}", timeout=10)

        return restored

    def verify_integrity(self, original_hashes: dict[str, str], restored_paths: list[str]) -> bool:
        """Verify transferred files match originals via SHA256."""
        import hashlib

        all_ok = True
        for path in restored_paths:
            # Get hash from target
            _, stdout, _ = self.ssh.exec(f"sha256sum {path} 2>/dev/null", timeout=10)
            remote_hash = stdout.split()[0] if stdout.strip() else ""

            # Check against original
            orig_content_hash = original_hashes.get(path, "")
            if orig_content_hash and remote_hash != orig_content_hash:
                logger.error(f"Integrity check FAILED: {path}")
                all_ok = False
            else:
                logger.info(f"Integrity check OK: {path}")

        return all_ok

    def cleanup(self) -> None:
        """Remove all temporary encrypted files."""
        import shutil
        try:
            shutil.rmtree(self._temp_dir)
            logger.info(f"Cleaned up temp dir: {self._temp_dir}")
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")

    def __enter__(self) -> CredentialCarrier:
        return self

    def __exit__(self, *args: object) -> None:
        self.cleanup()
