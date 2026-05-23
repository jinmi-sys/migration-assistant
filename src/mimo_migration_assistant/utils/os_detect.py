"""OS and environment detection utilities."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from ..models.machine import OSType


def detect_os() -> OSType:
    """Detect current OS type."""
    system = platform.system().lower()
    if system != "linux":
        return OSType.UNKNOWN

    # Check Termux
    if Path("/data/data/com.termux").exists():
        return OSType.TERMUX

    # Check WSL2
    try:
        with open("/proc/version") as f:
            if "microsoft" in f.read().lower():
                return OSType.WSL2
    except FileNotFoundError:
        pass

    # Check distro
    try:
        with open("/etc/os-release") as f:
            content = f.read().lower()
            if "ubuntu" in content:
                return OSType.UBUNTU
            if "debian" in content:
                return OSType.DEBIAN
            if "centos" in content or "rhel" in content:
                return OSType.CENTOS
    except FileNotFoundError:
        pass

    return OSType.UNKNOWN


def detect_package_manager() -> str:
    """Detect system package manager."""
    os_type = detect_os()
    if os_type in (OSType.UBUNTU, OSType.DEBIAN, OSType.WSL2):
        return "apt"
    if os_type == OSType.CENTOS:
        return "yum"
    if os_type == OSType.TERMUX:
        return "pkg"
    return "unknown"


def get_systemd_services() -> list[str]:
    """List active systemd services."""
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--plain"],
            capture_output=True, text=True, timeout=10,
        )
        services = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts and parts[0].endswith(".service"):
                services.append(parts[0].replace(".service", ""))
        return services
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def get_listening_ports() -> list[dict]:
    """Get list of listening ports with PIDs."""
    try:
        result = subprocess.run(
            ["ss", "-tlnp"], capture_output=True, text=True, timeout=10,
        )
        ports = []
        for line in result.stdout.splitlines()[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 4:
                addr = parts[3]
                port_str = addr.rsplit(":", 1)[-1] if ":" in addr else addr
                pid_info = parts[-1] if "pid=" in parts[-1] else ""
                pid = int(pid_info.split("pid=")[1].split(",")[0]) if "pid=" in pid_info else None
                try:
                    ports.append({"port": int(port_str), "pid": pid, "address": addr.rsplit(":", 1)[0]})
                except ValueError:
                    continue
        return ports
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
