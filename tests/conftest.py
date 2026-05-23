"""Shared fixtures for mimo-migration-assistant tests."""

from __future__ import annotations

import pytest

from mimo_migration_assistant.models.machine import MachineSpec, OSType
from mimo_migration_assistant.models.service import ServiceInfo, ServiceStatus, PortMapping
from mimo_migration_assistant.models.migration import MigrationPlan, MigrationStep, StepType, MigrationStatus
from mimo_migration_assistant.scraper.environment import EnvironmentTelemetry


@pytest.fixture
def sample_machine_source() -> MachineSpec:
    return MachineSpec(
        hostname="old-server",
        os_type=OSType.UBUNTU,
        os_version="22.04",
        kernel="5.15.0-generic",
        arch="x86_64",
        total_memory_mb=8192,
        cpu_cores=4,
        disk_free_gb=120.5,
        docker_installed=True,
        docker_version="24.0.7",
        python_version="3.11.5",
    )


@pytest.fixture
def sample_machine_target() -> MachineSpec:
    return MachineSpec(
        hostname="new-server",
        os_type=OSType.DEBIAN,
        os_version="12",
        kernel="6.1.0-generic",
        arch="x86_64",
        total_memory_mb=16384,
        cpu_cores=8,
        disk_free_gb=500.0,
        docker_installed=True,
        docker_version="25.0.3",
        python_version="3.12.1",
    )


@pytest.fixture
def sample_services() -> list[ServiceInfo]:
    return [
        ServiceInfo(
            name="nginx",
            status=ServiceStatus.RUNNING,
            pid=1234,
            ports=[PortMapping(port=80), PortMapping(port=443)],
            config_files=["/etc/nginx/nginx.conf"],
            systemd_unit="nginx.service",
        ),
        ServiceInfo(
            name="redis-server",
            status=ServiceStatus.RUNNING,
            pid=5678,
            ports=[PortMapping(port=6379)],
            config_files=["/etc/redis/redis.conf"],
            systemd_unit="redis-server.service",
            data_dirs=["/var/lib/redis"],
        ),
        ServiceInfo(
            name="ollama",
            status=ServiceStatus.RUNNING,
            pid=9012,
            ports=[PortMapping(port=11434)],
            docker_container="ollama",
            docker_image="ollama/ollama:latest",
        ),
    ]


@pytest.fixture
def sample_telemetry_source(sample_machine_source, sample_services) -> EnvironmentTelemetry:
    return EnvironmentTelemetry(
        machine=sample_machine_source,
        services=sample_services,
        env_files={"/opt/app/.env": "DB_HOST=localhost\nDB_PASS=secret"},
        port_map={80: "nginx", 443: "nginx", 6379: "redis-server", 11434: "ollama"},
        systemd_units=["nginx", "redis-server"],
        docker_containers=[{"name": "ollama", "image": "ollama/ollama:latest"}],
    )


@pytest.fixture
def sample_telemetry_target(sample_machine_target) -> EnvironmentTelemetry:
    return EnvironmentTelemetry(
        machine=sample_machine_target,
        services=[],
        env_files={},
        port_map={},
        systemd_units=[],
        docker_containers=[],
    )


@pytest.fixture
def sample_plan() -> MigrationPlan:
    return MigrationPlan(
        id="test-plan-001",
        source_host="old-server",
        target_host="new-server",
        services=["nginx", "redis-server", "ollama"],
        steps=[
            MigrationStep(
                id=1,
                step_type=StepType.STOP_SERVICE,
                description="Stop nginx",
                command="systemctl stop nginx",
                target="source",
                rollback_command="systemctl start nginx",
            ),
            MigrationStep(
                id=2,
                step_type=StepType.STOP_SERVICE,
                description="Stop redis-server",
                command="systemctl stop redis-server",
                target="source",
                depends_on=[1],
                rollback_command="systemctl start redis-server",
            ),
            MigrationStep(
                id=3,
                step_type=StepType.COMPRESS_DATA,
                description="Compress nginx data",
                command="tar czf /tmp/migrate_nginx.tar.gz /etc/nginx",
                target="source",
                depends_on=[1],
            ),
            MigrationStep(
                id=4,
                step_type=StepType.TRANSFER_FILE,
                description="Transfer nginx archive",
                command="# scp /tmp/migrate_nginx.tar.gz target:/tmp/",
                target="source",
                depends_on=[3],
            ),
            MigrationStep(
                id=5,
                step_type=StepType.HEALTH_CHECK,
                description="Health check nginx",
                command="curl -sf http://localhost:80/",
                target="target",
                depends_on=[4],
                critical=False,
            ),
        ],
    )


@pytest.fixture
def mock_ssh(monkeypatch):
    """Mock SSH client that returns canned responses."""
    class MockSSH:
        def __init__(self):
            self.commands = []

        def exec(self, command, timeout=30):
            self.commands.append(command)
            if "systemctl is-active" in command:
                return 0, "active", ""
            if "ss -tlnp" in command:
                return 0, "LISTEN  0  128  0.0.0.0:80  0.0.0.0:*  users:((\"nginx\",pid=1234,fd=6))", ""
            if "docker ps" in command:
                return 0, '{"name":"ollama","image":"ollama/ollama:latest","status":"Up 2 days"}', ""
            return 0, "", ""

        def connect(self):
            pass

        def close(self):
            pass

        def upload(self, local, remote):
            pass

        def download(self, remote, local):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return MockSSH()
