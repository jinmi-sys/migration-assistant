"""SSH client wrapper using paramiko."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import paramiko

from ..models.machine import MachineSpec


@dataclass
class SSHConfig:
    """SSH connection configuration."""

    hostname: str
    port: int = 22
    username: str = "root"
    key_file: Optional[str] = None
    password: Optional[str] = None
    timeout: int = 30
    jump_host: Optional[str] = None

    @classmethod
    def from_uri(cls, uri: str) -> SSHConfig:
        """Parse ssh://user@host:port format."""
        uri = uri.replace("ssh://", "")
        user, rest = uri.split("@", 1) if "@" in uri else ("root", uri)
        host, port = (rest.split(":", 1) + ["22"])[:2]
        return cls(hostname=host, port=int(port), username=user)


class SSHClient:
    """Paramiko-based SSH client for migration operations."""

    def __init__(self, config: SSHConfig) -> None:
        self.config = config
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None

    def connect(self) -> None:
        """Establish SSH connection."""
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs: dict = {
            "hostname": self.config.hostname,
            "port": self.config.port,
            "username": self.config.username,
            "timeout": self.config.timeout,
        }
        if self.config.key_file:
            kwargs["key_filename"] = self.config.key_file
        elif self.config.password:
            kwargs["password"] = self.config.password

        self._client.connect(**kwargs)
        self._sftp = self._client.open_sftp()

    def close(self) -> None:
        if self._sftp:
            self._sftp.close()
        if self._client:
            self._client.close()

    def __enter__(self) -> SSHClient:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def exec(self, command: str, timeout: int = 300) -> tuple[int, str, str]:
        """Execute command on remote machine. Returns (exit_code, stdout, stderr)."""
        if not self._client:
            raise RuntimeError("SSH not connected")
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, stdout.read().decode(), stderr.read().decode()

    def upload(self, local_path: str, remote_path: str) -> None:
        """Upload file via SFTP."""
        if not self._sftp:
            raise RuntimeError("SFTP not connected")
        os.makedirs(os.path.dirname(remote_path) or ".", exist_ok=True)
        self._sftp.put(local_path, remote_path)

    def download(self, remote_path: str, local_path: str) -> None:
        """Download file via SFTP."""
        if not self._sftp:
            raise RuntimeError("SFTP not connected")
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        self._sftp.get(remote_path, local_path)

    def upload_string(self, content: str, remote_path: str) -> None:
        """Upload string content as file."""
        if not self._sftp:
            raise RuntimeError("SFTP not connected")
        with self._sftp.open(remote_path, "w") as f:
            f.write(content)

    def read_file(self, remote_path: str) -> str:
        """Read remote file content."""
        if not self._sftp:
            raise RuntimeError("SFTP not connected")
        with self._sftp.open(remote_path, "r") as f:
            return f.read()

    def get_machine_spec(self) -> MachineSpec:
        """Gather machine specifications via SSH."""
        scripts = {
            "os": "cat /etc/os-release 2>/dev/null || uname -s",
            "kernel": "uname -r",
            "arch": "uname -m",
            "memory": "free -m | awk '/Mem:/ {print $2}'",
            "cpu": "nproc",
            "disk": "df -BG / | awk 'NR==2 {print $4}' | tr -d 'G'",
            "docker": "docker --version 2>/dev/null || echo none",
            "python": "python3 --version 2>/dev/null || echo none",
            "shell": "echo $SHELL",
            "hostname": "hostname",
        }
        results = {}
        for key, cmd in scripts.items():
            _, stdout, _ = self.exec(cmd, timeout=10)
            results[key] = stdout.strip()

        from ..models.machine import OSType
        os_raw = results["os"].lower()
        if "ubuntu" in os_raw or "wsl" in os_raw:
            os_type = OSType.WSL2 if "microsoft" in os_raw else OSType.UBUNTU
        elif "debian" in os_raw:
            os_type = OSType.DEBIAN
        elif "centos" in os_raw or "rhel" in os_raw:
            os_type = OSType.CENTOS
        else:
            os_type = OSType.UNKNOWN

        docker_str = results["docker"]
        docker_installed = docker_str != "none"
        docker_version = docker_str.split("version ")[-1].split(",")[0] if docker_installed else ""

        return MachineSpec(
            hostname=results["hostname"],
            os_type=os_type,
            kernel=results["kernel"],
            arch=results["arch"],
            total_memory_mb=int(results["memory"] or 0),
            cpu_cores=int(results["cpu"] or 1),
            disk_free_gb=float(results["disk"] or 0),
            docker_installed=docker_installed,
            docker_version=docker_version,
            python_version=results["python"],
            shell=results["shell"] or "/bin/bash",
            user=self.config.username,
            ssh_port=self.config.port,
        )
