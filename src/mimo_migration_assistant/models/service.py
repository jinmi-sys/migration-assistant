"""Service definition models."""

from __future__ import annotations

import enum
from pathlib import PurePosixPath
from typing import Optional

from pydantic import BaseModel, Field


class ServiceStatus(str, enum.Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


class PortMapping(BaseModel):
    """Port binding information."""

    port: int
    protocol: str = "tcp"
    bind_address: str = "0.0.0.0"
    service_name: str = ""
    pid: Optional[int] = None


class ServiceInfo(BaseModel):
    """Complete description of a discovered service."""

    name: str
    status: ServiceStatus = ServiceStatus.UNKNOWN
    pid: Optional[int] = None
    ports: list[PortMapping] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    env_files: list[str] = Field(default_factory=list)
    working_dir: str = ""
    executable: str = ""
    systemd_unit: Optional[str] = None
    docker_container: Optional[str] = None
    docker_image: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    data_dirs: list[str] = Field(default_factory=list)
    log_files: list[str] = Field(default_factory=list)

    @property
    def primary_port(self) -> Optional[int]:
        return self.ports[0].port if self.ports else None

    @property
    def is_dockerized(self) -> bool:
        return self.docker_container is not None
