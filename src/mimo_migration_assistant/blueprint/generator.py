"""MiMo-powered Migration Blueprint Generator.

Takes environment telemetry from source and target machines,
uses MiMo-V2.5-Pro reasoning to generate an ordered migration plan.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from ..models.migration import MigrationPlan, MigrationStep, StepType
from ..models.machine import MachineSpec
from ..scraper.environment import EnvironmentTelemetry
from .templates import ScriptTemplate

logger = logging.getLogger(__name__)

BLUEPRINT_PROMPT = """You are an expert DevOps migration engineer. Given the source and target machine specifications, generate a safe, ordered migration plan.

SOURCE MACHINE:
{source_spec}

TARGET MACHINE:
{target_spec}

SERVICES TO MIGRATE:
{services}

SOURCE ENV FILES (paths only, content is encrypted):
{env_paths}

PORT CONFLICTS DETECTED:
{port_conflicts}

RULES:
1. Always stop services on source BEFORE compressing data
2. Transfer compressed archives, not individual files
3. Set permissions AFTER extracting on target
4. Configure firewall BEFORE starting services
5. Health-check EVERY service after start
6. Include rollback commands for critical steps
7. Account for OS differences (apt vs pkg, systemd vs proot)
8. Never include credentials in commands - reference env files by path

Output a JSON migration plan with this structure:
{{
  "steps": [
    {{
      "id": 1,
      "step_type": "stop_service",
      "description": "...",
      "command": "...",
      "target": "source",
      "depends_on": [],
      "timeout_seconds": 30,
      "rollback_command": "...",
      "critical": true
    }}
  ],
  "port_mappings": {{}},
  "notes": "..."
}}

Output ONLY valid JSON. No markdown, no explanation.
"""


class BlueprintGenerator:
    """Generates migration plans using MiMo-V2.5-Pro."""

    def __init__(
        self,
        mimo_api_url: str = "http://localhost:11434/v1/chat/completions",
        mimo_model: str = "mimo-v2.5-pro",
        api_key: Optional[str] = None,
    ) -> None:
        self.api_url = mimo_api_url
        self.model = mimo_model
        self.api_key = api_key

    def generate(
        self,
        source: EnvironmentTelemetry,
        target: EnvironmentTelemetry,
        service_filter: Optional[list[str]] = None,
    ) -> MigrationPlan:
        """Generate migration plan from source to target telemetry."""
        logger.info("Generating migration blueprint via MiMo")

        # Detect port conflicts
        port_conflicts = self._detect_port_conflicts(source, target)

        # Build prompt
        prompt = self._build_prompt(source, target, service_filter, port_conflicts)

        # Call MiMo
        plan_json = self._call_mimo(prompt)

        # Parse into MigrationPlan
        plan = self._parse_plan(plan_json, source, target, port_conflicts)

        logger.info(f"Blueprint generated: {plan.total_steps} steps")
        return plan

    def generate_offline(
        self,
        source: EnvironmentTelemetry,
        target: EnvironmentTelemetry,
        service_filter: Optional[list[str]] = None,
    ) -> MigrationPlan:
        """Generate plan without LLM - uses template-based approach."""
        logger.info("Generating offline migration blueprint (template-based)")

        services = source.services
        if service_filter:
            services = [s for s in services if s.name in service_filter]

        port_conflicts = self._detect_port_conflicts(source, target)
        steps: list[MigrationStep] = []
        step_id = 0
        port_mappings: dict[int, int] = {}

        # 1. Stop services
        for svc in services:
            step_id += 1
            if svc.is_dockerized:
                cmd = f"docker stop {svc.docker_container}"
            elif svc.systemd_unit:
                cmd = f"systemctl stop {svc.name}"
            else:
                cmd = f"kill {svc.pid}" if svc.pid else f"pkill -f {svc.name}"
            steps.append(MigrationStep(
                id=step_id,
                step_type=StepType.STOP_SERVICE,
                description=f"Stop {svc.name}",
                command=cmd,
                target="source",
                rollback_command=cmd.replace("stop", "start").replace("kill", "true"),
            ))

        # 2. Compress data
        for svc in services:
            step_id += 1
            data_paths = svc.data_dirs + svc.config_files + svc.env_files
            if data_paths:
                archive = f"/tmp/migrate_{svc.name}.tar.gz"
                paths_str = " ".join(data_paths)
                steps.append(MigrationStep(
                    id=step_id,
                    step_type=StepType.COMPRESS_DATA,
                    description=f"Compress {svc.name} data",
                    command=f"tar czf {archive} {paths_str}",
                    target="source",
                    depends_on=[s.id for s in steps if s.step_type == StepType.STOP_SERVICE and s.description.endswith(svc.name)],
                ))

        # 3. Transfer
        for svc in services:
            step_id += 1
            archive = f"/tmp/migrate_{svc.name}.tar.gz"
            steps.append(MigrationStep(
                id=step_id,
                step_type=StepType.TRANSFER_FILE,
                description=f"Transfer {svc.name} archive to target",
                command=f"# Transfer {archive} via SCP/rsync",
                target="source",
                depends_on=[s.id for s in steps if s.step_type == StepType.COMPRESS_DATA and s.description.endswith(svc.name)],
            ))

        # 4. Install packages on target
        step_id += 1
        pkg_mgr = target.machine.package_manager
        packages = set()
        for svc in services:
            if svc.name in SERVICE_DEPS:
                packages.update(SERVICE_DEPS[svc.name])
        if packages:
            pkg_cmd = f"{pkg_mgr} install -y {' '.join(packages)}" if pkg_mgr != "unknown" else "# Install packages manually"
            steps.append(MigrationStep(
                id=step_id,
                step_type=StepType.INSTALL_PACKAGE,
                description=f"Install dependencies on target",
                command=pkg_cmd,
                target="target",
            ))

        # 5. Extract on target
        for svc in services:
            step_id += 1
            archive = f"/tmp/migrate_{svc.name}.tar.gz"
            steps.append(MigrationStep(
                id=step_id,
                step_type=StepType.CONFIGURE_SERVICE,
                description=f"Extract {svc.name} data on target",
                command=f"tar xzf {archive} -C /",
                target="target",
                depends_on=[s.id for s in steps if s.step_type == StepType.TRANSFER_FILE and s.description.endswith(svc.name)],
            ))

        # 6. Port conflict resolution
        for old_port, new_port in port_conflicts.items():
            port_mappings[old_port] = new_port
            step_id += 1
            steps.append(MigrationStep(
                id=step_id,
                step_type=StepType.CONFIGURE_FIREWALL,
                description=f"Remap port {old_port} -> {new_port}",
                command=f"# Update config to use port {new_port} instead of {old_port}",
                target="target",
            ))

        # 7. Set permissions
        step_id += 1
        steps.append(MigrationStep(
            id=step_id,
            step_type=StepType.SET_PERMISSIONS,
            description="Fix file permissions on target",
            command="# chmod/chown as needed per service",
            target="target",
        ))

        # 8. Start services
        for svc in services:
            step_id += 1
            if svc.is_dockerized:
                cmd = f"docker start {svc.docker_container}"
            elif svc.systemd_unit:
                cmd = f"systemctl start {svc.name}"
            else:
                cmd = f"# Start {svc.name} manually"
            steps.append(MigrationStep(
                id=step_id,
                step_type=StepType.START_SERVICE,
                description=f"Start {svc.name} on target",
                command=cmd,
                target="target",
                depends_on=[s.id for s in steps if s.step_type == StepType.SET_PERMISSIONS],
            ))

        # 9. Health checks
        for svc in services:
            step_id += 1
            port = svc.primary_port
            if port:
                new_port = port_mappings.get(port, port)
                cmd = f"curl -sf http://localhost:{new_port}/health || curl -sf http://localhost:{new_port}/"
            else:
                cmd = f"systemctl is-active {svc.name}" if svc.systemd_unit else f"pgrep -f {svc.name}"
            steps.append(MigrationStep(
                id=step_id,
                step_type=StepType.HEALTH_CHECK,
                description=f"Health check {svc.name}",
                command=cmd,
                target="target",
                depends_on=[s.id for s in steps if s.step_type == StepType.START_SERVICE and s.description.endswith(svc.name)],
                critical=False,
            ))

        return MigrationPlan(
            source_host=source.machine.hostname,
            target_host=target.machine.hostname,
            services=[s.name for s in services],
            steps=steps,
            port_mappings=port_mappings,
            notes="Generated in offline/template mode. Review before executing.",
        )

    def _detect_port_conflicts(
        self, source: EnvironmentTelemetry, target: EnvironmentTelemetry
    ) -> dict[int, int]:
        """Find ports that conflict between source services and target's existing services."""
        target_ports = set(target.port_map.keys())
        conflicts: dict[int, int] = {}

        for svc in source.services:
            for p in svc.ports:
                if p.port in target_ports and target.port_map[p.port] != svc.name:
                    # Find next available port
                    new_port = p.port + 1000
                    while new_port in target_ports:
                        new_port += 1
                    conflicts[p.port] = new_port
                    logger.warning(f"Port conflict: {p.port} ({svc.name}) -> {new_port}")

        return conflicts

    def _build_prompt(
        self,
        source: EnvironmentTelemetry,
        target: EnvironmentTelemetry,
        service_filter: Optional[list[str]],
        port_conflicts: dict[int, int],
    ) -> str:
        services = source.services
        if service_filter:
            services = [s for s in services if s.name in service_filter]

        return BLUEPRINT_PROMPT.format(
            source_spec=json.dumps(source.machine.model_dump(), indent=2),
            target_spec=json.dumps(target.machine.model_dump(), indent=2),
            services=", ".join(s.name for s in services),
            env_paths=", ".join(source.env_files.keys()),
            port_conflicts=json.dumps(port_conflicts) if port_conflicts else "None",
        )

    def _call_mimo(self, prompt: str) -> str:
        """Call MiMo API for plan generation."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 8192,
        }

        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(self.api_url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"MiMo API call failed: {e}")
            raise

    def _parse_plan(
        self,
        plan_json: str,
        source: EnvironmentTelemetry,
        target: EnvironmentTelemetry,
        port_conflicts: dict[int, int],
    ) -> MigrationPlan:
        """Parse LLM output into MigrationPlan."""
        # Strip markdown fences if present
        clean = plan_json.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]

        data = json.loads(clean)

        steps = []
        for s in data.get("steps", []):
            steps.append(MigrationStep(
                id=s["id"],
                step_type=StepType(s["step_type"]),
                description=s["description"],
                command=s.get("command", ""),
                target=s.get("target", "source"),
                depends_on=s.get("depends_on", []),
                timeout_seconds=s.get("timeout_seconds", 300),
                rollback_command=s.get("rollback_command"),
                critical=s.get("critical", True),
            ))

        return MigrationPlan(
            source_host=source.machine.hostname,
            target_host=target.machine.hostname,
            services=[s.name for s in source.services],
            steps=steps,
            port_mappings=data.get("port_mappings", port_conflicts),
            notes=data.get("notes", ""),
        )


# Service dependency map for offline mode
SERVICE_DEPS: dict[str, list[str]] = {
    "ollama": [],
    "nginx": ["nginx"],
    "redis-server": ["redis-server"],
    "postgresql": ["postgresql", "postgresql-client"],
    "docker": ["docker.io", "docker-compose-plugin"],
}
