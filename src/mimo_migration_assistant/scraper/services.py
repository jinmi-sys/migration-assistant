"""Service discovery - detects running services, ports, and configurations."""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

from ..models.service import ServiceInfo, ServiceStatus, PortMapping

# Known service patterns for intelligent detection
SERVICE_PATTERNS = {
    "ollama": {
        "ports": [11434],
        "config_patterns": [".ollama", "OLLAMA_HOST"],
        "systemd": "ollama",
    },
    "openclaw": {
        "ports": [8000],
        "config_patterns": ["openclaw", "OPENCLAW"],
        "systemd": "openclaw",
    },
    "nginx": {
        "ports": [80, 443],
        "config_patterns": ["nginx.conf", "sites-enabled"],
        "systemd": "nginx",
    },
    "redis": {
        "ports": [6379],
        "config_patterns": ["redis.conf"],
        "systemd": "redis-server",
    },
    "postgres": {
        "ports": [5432],
        "config_patterns": ["postgresql.conf", "pg_hba.conf"],
        "systemd": "postgresql",
    },
    "docker": {
        "ports": [2375, 2376],
        "config_patterns": ["daemon.json"],
        "systemd": "docker",
    },
}


class ServiceDiscovery:
    """Discovers running services on a machine via shell commands."""

    def __init__(self, run_fn: Callable[[str, int], str]) -> None:
        self._run = run_fn

    def discover(self, service_filter: Optional[list[str]] = None) -> list[ServiceInfo]:
        """Discover all running services."""
        services: list[ServiceInfo] = []
        seen_names: set[str] = set()

        # 1. From systemd
        for svc in self._discover_systemd():
            if svc.name not in seen_names:
                if service_filter is None or svc.name in service_filter:
                    services.append(svc)
                    seen_names.add(svc.name)

        # 2. From listening ports
        for svc in self._discover_from_ports():
            if svc.name not in seen_names:
                if service_filter is None or svc.name in service_filter:
                    services.append(svc)
                    seen_names.add(svc.name)

        # 3. From Docker
        for svc in self._discover_docker():
            if svc.name not in seen_names:
                if service_filter is None or svc.name in service_filter:
                    services.append(svc)
                    seen_names.add(svc.name)

        # 4. Enrich with config files and env files
        for svc in services:
            self._enrich_service(svc)

        return services

    def _discover_systemd(self) -> list[ServiceInfo]:
        """Discover services from systemd."""
        raw = self._run(
            "systemctl list-units --type=service --state=running --no-pager --plain 2>/dev/null",
            timeout=10,
        )
        services = []
        for line in raw.splitlines()[1:]:
            parts = line.split()
            if not parts or not parts[0].endswith(".service"):
                continue
            name = parts[0].replace(".service", "")
            svc = ServiceInfo(
                name=name,
                status=ServiceStatus.RUNNING,
                systemd_unit=parts[0],
            )
            # Get PID
            pid_raw = self._run(f"systemctl show {name} --property=MainPID --value 2>/dev/null", timeout=5)
            try:
                svc.pid = int(pid_raw.strip())
            except ValueError:
                pass
            services.append(svc)
        return services

    def _discover_from_ports(self) -> list[ServiceInfo]:
        """Discover services from listening ports."""
        raw = self._run("ss -tlnp 2>/dev/null", timeout=10)
        services = []
        for line in raw.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            addr = parts[3]
            port_str = addr.rsplit(":", 1)[-1] if ":" in addr else ""
            if not port_str:
                continue
            try:
                port = int(port_str)
            except ValueError:
                continue

            # Extract PID/process name
            pid = None
            process = ""
            for part in parts:
                if "pid=" in part:
                    try:
                        pid = int(part.split("pid=")[1].split(",")[0])
                    except ValueError:
                        pass
                if "users:" in part:
                    match = re.search(r'"([^"]+)"', part)
                    if match:
                        process = match.group(1)

            name = process or f"port-{port}"
            svc = ServiceInfo(
                name=name,
                status=ServiceStatus.RUNNING,
                pid=pid,
                ports=[PortMapping(port=port, bind_address=addr.rsplit(":", 1)[0], pid=pid, service_name=name)],
            )
            services.append(svc)
        return services

    def _discover_docker(self) -> list[ServiceInfo]:
        """Discover Docker containers."""
        raw = self._run(
            "docker ps --format '{\"name\":\"{{.Names}}\",\"image\":\"{{.Image}}\",\"ports\":\"{{.Ports}}\",\"status\":\"{{.Status}}\"}' 2>/dev/null",
            timeout=10,
        )
        services = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            ports = []
            for port_str in re.findall(r"0\.0\.0\.0:(\d+)->", data.get("ports", "")):
                ports.append(PortMapping(port=int(port_str), service_name=data["name"]))

            svc = ServiceInfo(
                name=data["name"],
                status=ServiceStatus.RUNNING,
                docker_container=data["name"],
                docker_image=data["image"],
                ports=ports,
            )
            services.append(svc)
        return services

    def _enrich_service(self, svc: ServiceInfo) -> None:
        """Add config files and env files to a service."""
        # Search for config files in common locations
        search_paths = ["/etc", "/opt", "/srv", f"/home"]
        for base in search_paths:
            raw = self._run(
                f"find {base} -maxdepth 3 -name '*.env' -o -name '.env' -o -name '{svc.name}.conf' 2>/dev/null",
                timeout=10,
            )
            for path in raw.splitlines():
                path = path.strip()
                if not path:
                    continue
                if ".env" in path:
                    svc.env_files.append(path)
                else:
                    svc.config_files.append(path)

        # Check for data directories
        for path in [f"/var/lib/{svc.name}", f"/opt/{svc.name}/data", f"/srv/{svc.name}"]:
            exists = self._run(f"test -d {path} && echo yes || echo no", timeout=5).strip()
            if exists == "yes":
                svc.data_dirs.append(path)
