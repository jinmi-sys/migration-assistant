"""Shell command execution helpers."""

from __future__ import annotations

import subprocess
import shlex
from typing import Optional

from .ssh import SSHClient


def quote_shell(cmd: str) -> str:
    """Quote a shell command for safe embedding in another shell invocation."""
    return shlex.quote(cmd)


def run_local(
    cmd: str,
    *,
    timeout: int = 300,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a command locally via ``/bin/bash``."""
    result = subprocess.run(
        cmd,
        shell=True,
        executable="/bin/bash",
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {cmd}\n"
            f"stderr: {result.stderr}"
        )
    return result


def run_remote(
    client: SSHClient,
    cmd: str,
    *,
    timeout: int = 300,
    check: bool = True,
) -> str:
    """Run a command on a remote host via SSH and return stdout."""
    exit_code, stdout, stderr = client.exec(cmd, timeout=timeout)
    if check and exit_code != 0:
        raise RuntimeError(
            f"Remote command failed ({exit_code}): {cmd}\n"
            f"stderr: {stderr}"
        )
    return stdout
