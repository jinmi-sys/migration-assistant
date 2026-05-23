from .ssh import SSHClient, SSHConfig
from .crypto import encrypt_file, decrypt_file, generate_key
from .os_detect import detect_os, detect_package_manager
from .shell import run_local, run_remote, quote_shell

__all__ = [
    "SSHClient", "SSHConfig",
    "encrypt_file", "decrypt_file", "generate_key",
    "detect_os", "detect_package_manager",
    "run_local", "run_remote", "quote_shell",
]
