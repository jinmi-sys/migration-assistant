"""Lifecycle Validator - post-migration health checks for all services."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from ..models.migration import MigrationPlan
from ..models.service import ServiceInfo, ServiceStatus
from ..utils.ssh import SSHClient

logger = logging.getLogger(__name__)


@dataclass
class HealthReport:
    """Report of post-migration health status."""

    service_name: str
    healthy: bool
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)
    response_time_ms: float = 0.0
    details: str = ""

    @property
    def status_icon(self) -> str:
        return "OK" if self.healthy else "FAIL"


@dataclass
class MigrationHealthReport:
    """Complete health report for all migrated services."""

    plan_id: str
    timestamp: float = field(default_factory=time.time)
    reports: list[HealthReport] = field(default_factory=list)
    overall_healthy: bool = True
    duration_seconds: float = 0.0

    @property
    def total_services(self) -> int:
        return len(self.reports)

    @property
    def healthy_count(self) -> int:
        return sum(1 for r in self.reports if r.healthy)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.reports if not r.healthy)

    def summary(self) -> str:
        lines = [
            f"Migration Health Report: {self.plan_id}",
            f"Services: {self.healthy_count}/{self.total_services} healthy",
            f"Duration: {self.duration_seconds:.1f}s",
            "",
        ]
        for r in self.reports:
            lines.append(f"  [{r.status_icon}] {r.service_name}")
            if r.checks_failed:
                for check in r.checks_failed:
                    lines.append(f"      FAILED: {check}")
        return "\n".join(lines)


class LifecycleValidator:
    """Validates that all services are running correctly after migration."""

    # Retry config
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds

    def __init__(self, ssh: SSHClient) -> None:
        self.ssh = ssh

    def validate(self, plan: MigrationPlan, services: list[ServiceInfo]) -> MigrationHealthReport:
        """Run health checks for all migrated services.

        Checks:
        1. Process/container running
        2. Port listening
        3. HTTP health endpoint responding
        4. Systemd unit active
        """
        start = time.time()
        report = MigrationHealthReport(plan_id=plan.id)

        for svc in services:
            health = self._check_service(svc, plan.port_mappings)
            report.reports.append(health)
            if not health.healthy:
                report.overall_healthy = False

        report.duration_seconds = time.time() - start
        logger.info(report.summary())
        return report

    def _check_service(self, svc: ServiceInfo, port_mappings: dict[int, int]) -> HealthReport:
        """Run all health checks for a single service."""
        report = HealthReport(service_name=svc.name, healthy=True)

        # Check 1: Process/container running
        if svc.is_dockerized:
            ok = self._check_docker(svc.docker_container or svc.name)
            if ok:
                report.checks_passed.append("docker_running")
            else:
                report.checks_failed.append("docker_not_running")
                report.healthy = False
        elif svc.systemd_unit:
            ok = self._check_systemd(svc.name)
            if ok:
                report.checks_passed.append("systemd_active")
            else:
                report.checks_failed.append("systemd_inactive")
                report.healthy = False
        elif svc.pid:
            ok = self._check_process(svc.name)
            if ok:
                report.checks_passed.append("process_running")
            else:
                report.checks_failed.append("process_not_running")
                report.healthy = False

        # Check 2: Port listening
        if svc.primary_port:
            port = port_mappings.get(svc.primary_port, svc.primary_port)
            ok = self._check_port(port)
            if ok:
                report.checks_passed.append(f"port_{port}_listening")
            else:
                report.checks_failed.append(f"port_{port}_not_listening")
                report.healthy = False

            # Check 3: HTTP health endpoint
            if ok:
                start = time.time()
                http_ok = self._check_http(port)
                report.response_time_ms = (time.time() - start) * 1000
                if http_ok:
                    report.checks_passed.append("http_responding")
                else:
                    report.checks_failed.append("http_not_responding")
                    # Not critical for all services

        return report

    def _check_systemd(self, name: str) -> bool:
        """Check if systemd unit is active."""
        for attempt in range(self.MAX_RETRIES):
            _, stdout, _ = self.ssh.exec(f"systemctl is-active {name} 2>/dev/null", timeout=10)
            if stdout.strip() == "active":
                return True
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(self.RETRY_DELAY)
        return False

    def _check_docker(self, name: str) -> bool:
        """Check if Docker container is running."""
        _, stdout, _ = self.ssh.exec(f"docker inspect -f '{{{{.State.Running}}}}' {name} 2>/dev/null", timeout=10)
        return stdout.strip().lower() == "true"

    def _check_process(self, name: str) -> bool:
        """Check if process is running by name."""
        _, stdout, _ = self.ssh.exec(f"pgrep -f {name} 2>/dev/null", timeout=10)
        return bool(stdout.strip())

    def _check_port(self, port: int) -> bool:
        """Check if port is listening."""
        for attempt in range(self.MAX_RETRIES):
            _, stdout, _ = self.ssh.exec(f"ss -tlnp | grep ':{port} ' 2>/dev/null", timeout=10)
            if stdout.strip():
                return True
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(self.RETRY_DELAY)
        return False

    def _check_http(self, port: int) -> bool:
        """Check HTTP endpoint responds."""
        _, stdout, _ = self.ssh.exec(
            f"curl -sf --max-time 5 http://localhost:{port}/health 2>/dev/null || "
            f"curl -sf --max-time 5 http://localhost:{port}/ 2>/dev/null || echo FAIL",
            timeout=15,
        )
        return stdout.strip() != "FAIL"
