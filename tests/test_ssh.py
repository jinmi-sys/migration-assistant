"""Tests for SSH utilities."""

import pytest

from mimo_migration_assistant.utils.ssh import SSHConfig


class TestSSHConfig:
    def test_from_uri_simple(self):
        config = SSHConfig.from_uri("ssh://root@example.com")
        assert config.hostname == "example.com"
        assert config.username == "root"
        assert config.port == 22

    def test_from_uri_with_port(self):
        config = SSHConfig.from_uri("ssh://admin@192.168.1.100:2222")
        assert config.hostname == "192.168.1.100"
        assert config.username == "admin"
        assert config.port == 2222

    def test_from_uri_no_user(self):
        config = SSHConfig.from_uri("ssh://myserver.com")
        assert config.hostname == "myserver.com"
        assert config.username == "root"

    def test_defaults(self):
        config = SSHConfig(hostname="test")
        assert config.port == 22
        assert config.username == "root"
        assert config.timeout == 30
        assert config.key_file is None
