"""Tests for credential carrier."""

import os
import tempfile

import pytest

from mimo_migration_assistant.utils.crypto import (
    generate_key, encrypt_file, decrypt_file, encrypt_string, decrypt_string,
)


class TestCrypto:
    def test_generate_key_with_passphrase(self):
        key, salt = generate_key("test-passphrase")
        assert len(key) > 0
        assert len(salt) == 16

    def test_generate_key_without_passphrase(self):
        key, salt = generate_key("")
        assert len(key) > 0
        assert len(salt) == 16

    def test_encrypt_decrypt_file(self):
        key, _ = generate_key()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("SECRET_DATA=abc123")
            in_path = f.name

        enc_path = in_path + ".enc"
        dec_path = in_path + ".dec"

        try:
            encrypt_file(in_path, enc_path, key)
            assert os.path.exists(enc_path)
            assert os.path.getsize(enc_path) > 0

            decrypt_file(enc_path, dec_path, key)
            content = open(dec_path).read()
            assert content == "SECRET_DATA=abc123"
        finally:
            for p in [in_path, enc_path, dec_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_encrypt_decrypt_string(self):
        key, _ = generate_key()
        original = "DB_HOST=localhost\nDB_PASS=supersecret"
        encrypted = encrypt_string(original, key)
        decrypted = decrypt_string(encrypted, key)
        assert decrypted == original

    def test_wrong_key_fails(self):
        key1, _ = generate_key()
        key2, _ = generate_key()
        encrypted = encrypt_string("test", key1)
        with pytest.raises(Exception):
            decrypt_string(encrypted, key2)


class TestCredentialCarrier:
    def test_prepare_secrets(self, mock_ssh):
        from mimo_migration_assistant.credential.carrier import CredentialCarrier

        with CredentialCarrier(mock_ssh, passphrase="test") as carrier:
            env_files = {
                "/opt/app/.env": "KEY=value",
                "/etc/redis/.env": "REDIS_PASS=secret",
            }
            encrypted = carrier.prepare_secrets(env_files)
            assert len(encrypted) == 2
            for p in encrypted:
                assert os.path.exists(p)
                assert p.endswith(".enc")

    def test_cleanup(self, mock_ssh):
        from mimo_migration_assistant.credential.carrier import CredentialCarrier

        carrier = CredentialCarrier(mock_ssh)
        temp_dir = carrier._temp_dir
        assert os.path.exists(temp_dir)
        carrier.cleanup()
        assert not os.path.exists(temp_dir)
