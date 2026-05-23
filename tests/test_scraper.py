"""Tests for environment scraper and service discovery."""

import pytest

from mimo_migration_assistant.scraper.services import ServiceDiscovery, SERVICE_PATTERNS
from mimo_migration_assistant.scraper.environment import EnvironmentScraper
from mimo_migration_assistant.models.service import ServiceStatus


class TestServiceDiscovery:
    def test_service_patterns_covered(self):
        assert "ollama" in SERVICE_PATTERNS
        assert "nginx" in SERVICE_PATTERNS
        assert "redis" in SERVICE_PATTERNS
        assert 11434 in SERVICE_PATTERNS["ollama"]["ports"]

    def test_discover_with_filter(self, mock_ssh):
        discovery = ServiceDiscovery(lambda cmd, *a, **kw: mock_ssh.exec(cmd)[1])
        services = discovery.discover(service_filter=["nginx"])
        for svc in services:
            assert svc.name == "nginx"


class TestEnvironmentScraper:
    def test_local_scraper(self):
        scraper = EnvironmentScraper(ssh=None)
        assert scraper._local is True

    def test_remote_scraper(self, mock_ssh):
        scraper = EnvironmentScraper(ssh=mock_ssh)
        assert scraper._local is False


class TestEnvironmentTelemetry:
    def test_to_dict_hides_secrets(self, sample_telemetry_source):
        d = sample_telemetry_source.to_dict()
        for path in d["env_files"]:
            assert d["env_files"][path] == "[ENCRYPTED]"

    def test_to_dict_has_services(self, sample_telemetry_source):
        d = sample_telemetry_source.to_dict()
        assert len(d["services"]) == 3
