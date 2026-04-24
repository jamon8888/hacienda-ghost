# src/piighost/install/service/linux.py
"""Linux systemd user-level service install/uninstall for piighost proxy.

Uses AmbientCapabilities=CAP_NET_BIND_SERVICE so the process can bind port 443
without running as root. The unit lives in ~/.config/systemd/user/.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from piighost.install.service import ServiceSpec

_SERVICE_NAME = "piighost-proxy.service"


def _unit_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "systemd" / "user"


def _unit_content(spec: ServiceSpec) -> str:
    return (
        "[Unit]\n"
        "Description=piighost anonymizing HTTPS proxy\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={spec.bin_path} proxy run"
        f" --port {spec.port}"
        f" --vault {spec.vault_dir}"
        f" --cert {spec.cert_path}"
        f" --key {spec.key_path}\n"
        "Restart=on-failure\n"
        "AmbientCapabilities=CAP_NET_BIND_SERVICE\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def install(spec: ServiceSpec) -> None:
    unit_dir = _unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / _SERVICE_NAME).write_text(_unit_content(spec), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", _SERVICE_NAME], check=True)


def uninstall(spec: ServiceSpec) -> None:
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", _SERVICE_NAME],
        check=False,
    )
    unit_path = _unit_dir() / _SERVICE_NAME
    if unit_path.exists():
        unit_path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def running(spec: ServiceSpec) -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", _SERVICE_NAME],
        capture_output=True,
    )
    return result.returncode == 0
