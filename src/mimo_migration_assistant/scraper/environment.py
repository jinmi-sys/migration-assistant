"""Environment Scraper Node - scans source machine for all migration-relevant data."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from ..models.machine import MachineSpec
from ..models.service import ServiceInfo, PortMapping, ServiceStatus
from ..utils.ssh import SSHClient
from .services import ServiceDiscovery

logger = logging.getLogger(__name__)


@dataclass
class EnvironmentTelemetry:
    """Complete snapshot of a machine's environment."""

    machine: MachineSpec
    services: list[ServiceInfo] = field(default_factory=list)
    env_files: dict[str, str] = field(default_factory=dict)  # path -> content
    port_map: dict[int, str] = field(default_factory=dict)  # port -> service name
    systemd_units: list[str] = field(default_factory=list)
    docker_containers: list[dict] = field(default_factory=list)
    cron_jobs: list[str] = field(default_factory=list)
    firewall_rules: list[str] = field(default_factory=list)
    nginx_configs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "machine": self.machine.model_dump(),
            "services": [s.model_dump() for s in self.services],
            "env_files": {k: "[ENCRYPTED]" for k in self.env_files},  # never dump secrets
            "port_map": self.port_map,
            "systemd_units": self.systemd_units,
            "docker_containers": self.docker_containers,
            "cron_jobs": self.cron_jobs,
            "firewall_rules": self.firewall_rules,
            "nginx_configs": self.nginx_configs,
        }


class EnvironmentScraper:
    """Scans a machine (local or remote via SSH) and collects full environment telemetry."""

    def __init__(self, ssh: Optional[SSHClient] = None) -> None:
        self.ssh = ssh
        self._local = ssh is None

    def _run(self, cmd: str, timeout: int = 30) -> str:
        """Run command locally or remotely."""
        if self._local:
            import subprocess
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
                return result.stdout
            except subprocess.TimeoutExpired:
                return ""
        else:
            _, stdout, _ = self.ssh.exec(cmd, timeout=timeout)  # type: ignore
            return stdout

    def scrape(self, service_filter: Optional[list[str]] = None) -> EnvironmentTelemetry:
        """Perform full environment scan."""
        logger.info("Starting environment scrape")

        # 1. Machine spec
        if self._local:
            from ..utils.os_detect import detect_os
            machine = self._local_machine_spec()
        else:
            machine = self.ssh.get_machine_spec()  # type: ignore

        logger.info(f"Machine: {machine.hostname} ({machine.os_type.value})")

        # 2. Discover services
        discovery = ServiceDiscovery(self._run)
        services = discovery.discover(service_filter)

        # 3. Collect .env files
        env_files = self._collect_env_files(services)

        # 4. Port map
        port_map = {}
        for svc in services:
            for p in svc.ports:
                port_map[p.port] = svc.name

        # 5. Systemd units
        systemd_raw = self._run("systemctl list-unit-files --type=service --no-pager --plain 2>/dev/null")
        systemd_units = [
            line.split()[0].replace(".service", "")
            for line in systemd_raw.splitlines()[1:]
            if line.strip() and ".service" in line
        ]

        # 6. Docker containers
        docker_raw = self._run("docker ps --format '{{json .}}' 2>/dev/null")
        docker_containers = []
        for line in docker_raw.splitlines():
            if line.strip():
                try:
                    docker_containers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        # 7. Cron jobs
        cron_raw = self._run("crontab -l 2>/dev/null || echo '")
        cron_jobs = [l for l in cron_raw.splitlines() if l.strip() and not l.startswith("#")]

        # 8. Firewall rules
        fw_raw = self._run("iptables -L -n 2>/dev/null || echo ''")
        firewall_rules = fw_raw.splitlines()[:50]  # cap at 50 lines

        # 9. Nginx configs
        nginx_raw = self._run("ls /etc/nginx/sites-enabled/ 2>/dev/null || echo ''")
        nginx_configs = [l.strip() for l in nginx_raw.splitlines() if l.strip()]

        telemetry = EnvironmentTelemetry(
            machine=machine,
            services=services,
            env_files=env_files,
            port_map=port_map,
            systemd_units=systemd_units[:100],
            docker_containers=docker_containers,
            cron_jobs=cron_jobs,
            firewall_rules=firewall_rules,
            nginx_configs=nginx_configs,
        )

        logger.info(f"Scrape complete: {len(services)} services, {len(env_files)} env files")
        return telemetry

    def _collect_env_files(self, services: list[ServiceInfo]) -> dict[str, str]:
        """Collect .env file contents from service directories."""
        env_files: dict[str, str] = {}
        seen_paths: set[str] = set()

        for svc in services:
            for ef in svc.env_files:
                if ef in seen_paths:
                    continue
                seen_paths.add(ef)
                content = self._run(f"cat {ef} 2>/dev/null")
                if content.strip():
                    env_files[ef] = content

        # Also scan common locations
        for pattern in ["/opt/*/.env", "/home/*/.env", "/srv/*/.env", "/etc/environment"]:
            raw = self._run(f"ls {pattern} 2>/dev/null")
            for path in raw.splitlines():
                path = path.strip()
                if path and path not in seen_paths:
                    seen_paths.add(path)
                    content = self._run(f"cat {path} 2>/dev/null")
                    if content.strip():
                        env_files[path] = content

        return env_files

    def _local_machine_spec(self) -> MachineSpec:
        """Gather local machine specs."""
        import platform
        import shutil
        from ..utils.os_detect import detect_os, get_listening_ports

        os_type = detect_os()
        mem_raw = shutil.disk_usage("/")
        total_mem = 0
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        total_mem = int(line.split()[1]) // 1024
                        break
        except FileNotFoundError:
            pass

        return MachineSpec(
            hostname=platform.node(),
            os_type=os_type,
            kernel=platform.release(),
            arch=platform.machine(),
            total_memory_mb=total_mem,
            cpu_cores=os.cpu_count() or 1,
            disk_free_gb=mem_raw.free / (1024 ** 3),
            docker_installed=shutil.which("docker") is not None,
            python_version=platform.python_version(),
            shell="/bin/bash",
        )
