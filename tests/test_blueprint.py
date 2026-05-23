"""Tests for blueprint generator."""

import pytest

from mimo_migration_assistant.blueprint.generator import BlueprintGenerator
from mimo_migration_assistant.blueprint.templates import ScriptTemplate
from mimo_migration_assistant.models.migration import MigrationStatus
from mimo_migration_assistant.models.service import ServiceInfo, PortMapping


class TestBlueprintGenerator:
    def test_generate_offline(self, sample_telemetry_source, sample_telemetry_target):
        gen = BlueprintGenerator()
        plan = gen.generate_offline(sample_telemetry_source, sample_telemetry_target)

        assert plan.total_steps > 0
        assert len(plan.services) == 3
        assert plan.source_host == "old-server"
        assert plan.target_host == "new-server"
        assert plan.status == MigrationStatus.PLANNED

    def test_generate_offline_with_filter(self, sample_telemetry_source, sample_telemetry_target):
        gen = BlueprintGenerator()
        plan = gen.generate_offline(
            sample_telemetry_source, sample_telemetry_target,
            service_filter=["nginx"],
        )
        assert plan.services == ["nginx"]

    def test_port_conflict_detection(self, sample_telemetry_source, sample_telemetry_target):
        sample_telemetry_target.port_map = {80: "apache2"}
        sample_telemetry_target.services = [
            ServiceInfo(name="apache2", ports=[PortMapping(port=80)])
        ]

        gen = BlueprintGenerator()
        conflicts = gen._detect_port_conflicts(sample_telemetry_source, sample_telemetry_target)
        assert 80 in conflicts
        assert conflicts[80] == 1080

    def test_offline_plan_has_rollback(self, sample_telemetry_source, sample_telemetry_target):
        gen = BlueprintGenerator()
        plan = gen.generate_offline(sample_telemetry_source, sample_telemetry_target)
        stop_steps = [s for s in plan.steps if s.step_type.value == "stop_service"]
        for step in stop_steps:
            assert step.rollback_command is not None

    def test_offline_plan_step_order(self, sample_telemetry_source, sample_telemetry_target):
        gen = BlueprintGenerator()
        plan = gen.generate_offline(sample_telemetry_source, sample_telemetry_target)
        stop_ids = [s.id for s in plan.steps if s.step_type.value == "stop_service"]
        compress_ids = [s.id for s in plan.steps if s.step_type.value == "compress_data"]
        if stop_ids and compress_ids:
            assert max(stop_ids) < min(compress_ids)


class TestScriptTemplate:
    def test_stop_systemd(self):
        result = ScriptTemplate.stop_service("nginx", systemd_unit="nginx.service")
        assert "systemctl stop nginx" in result

    def test_stop_docker(self):
        result = ScriptTemplate.stop_service("ollama", docker_container="ollama")
        assert "docker stop ollama" in result

    def test_compress(self):
        result = ScriptTemplate.compress("app", ["/opt/app", "/etc/app.conf"])
        assert "tar czf" in result
        assert "/opt/app" in result

    def test_health_check_port(self):
        result = ScriptTemplate.health_check("nginx", port=80)
        assert "curl" in result
        assert "80" in result

    def test_health_check_systemd(self):
        result = ScriptTemplate.health_check("redis", systemd_unit="redis.service")
        assert "systemctl is-active" in result
