"""Tests for data models."""

from mimo_migration_assistant.models.machine import MachineSpec, OSType
from mimo_migration_assistant.models.service import ServiceInfo, ServiceStatus, PortMapping
from mimo_migration_assistant.models.migration import (
    MigrationPlan, MigrationStep, StepType, MigrationStatus, MigrationResult,
)


class TestMachineSpec:
    def test_container_capable(self, sample_machine_source):
        assert sample_machine_source.is_container_capable is True

    def test_package_manager_ubuntu(self, sample_machine_source):
        assert sample_machine_source.package_manager == "apt"

    def test_package_manager_termux(self):
        m = MachineSpec(hostname="phone", os_type=OSType.TERMUX)
        assert m.package_manager == "pkg"
        assert m.is_container_capable is False

    def test_defaults(self):
        m = MachineSpec(hostname="test")
        assert m.os_type == OSType.UNKNOWN
        assert m.arch == "x86_64"
        assert m.ssh_port == 22


class TestServiceInfo:
    def test_primary_port(self, sample_services):
        assert sample_services[0].primary_port == 80
        assert sample_services[2].primary_port == 11434

    def test_no_ports(self):
        svc = ServiceInfo(name="cron")
        assert svc.primary_port is None

    def test_is_dockerized(self, sample_services):
        assert sample_services[0].is_dockerized is False
        assert sample_services[2].is_dockerized is True


class TestMigrationPlan:
    def test_progress(self, sample_plan):
        assert sample_plan.total_steps == 5
        assert sample_plan.completed_steps == 0
        assert sample_plan.progress_pct == 0.0

    def test_next_step(self, sample_plan):
        step = sample_plan.next_step()
        assert step is not None
        assert step.id == 1

    def test_next_step_with_completed(self, sample_plan):
        sample_plan.steps[0].completed = True
        step = sample_plan.next_step()
        assert step is not None
        assert step.id == 2

    def test_next_step_all_done(self, sample_plan):
        for s in sample_plan.steps:
            s.completed = True
        assert sample_plan.next_step() is None

    def test_status_default(self):
        plan = MigrationPlan()
        assert plan.status == MigrationStatus.PLANNED


class TestMigrationStep:
    def test_step_types(self):
        for st in StepType:
            step = MigrationStep(id=1, step_type=st, description="test")
            assert step.step_type == st

    def test_defaults(self):
        step = MigrationStep(id=1, step_type=StepType.HEALTH_CHECK, description="test")
        assert step.target == "source"
        assert step.critical is True
        assert step.completed is False
        assert step.timeout_seconds == 300
