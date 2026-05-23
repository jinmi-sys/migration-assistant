"""Machine and OS type definitions."""

from __future__ import annotations

import enum
from typing import Optional

from pydantic import BaseModel, Field


class OSType(str, enum.Enum):
    """Supported operating system types."""

    UBUNTU = "ubuntu"
    DEBIAN = "debian"
    CENTOS = "centos"
    WSL2 = "wsl2"
    TERMUX = "termux"
    UNKNOWN = "unknown"


class MachineSpec(BaseModel):
    """Full specification of a source or target machine."""

    hostname: str
    os_type: OSType = OSType.UNKNOWN
    os_version: str = ""
    kernel: str = ""
    arch: str = "x86_64"
    total_memory_mb: int = 0
    cpu_cores: int = 0
    disk_free_gb: float = 0.0
    docker_installed: bool = False
    docker_version: str = ""
    python_version: str = ""
    shell: str = "/bin/bash"
    user: str = "root"
    ssh_port: int = 22

    @property
    def is_container_capable(self) -> bool:
        return self.docker_installed and self.os_type not in (OSType.TERMUX,)

    @property
    def package_manager(self) -> str:
        if self.os_type in (OSType.UBUNTU, OSType.DEBIAN, OSType.WSL2):
            return "apt"
        if self.os_type == OSType.CENTOS:
            return "yum"
        if self.os_type == OSType.TERMUX:
            return "pkg"
        return "unknown"
