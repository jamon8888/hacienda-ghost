"""systemd --user backend for the piighost proxy auto-restart service."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from piighost.install.service.user_service import UserServiceSpec

_UNIT_NAME = "piighost-proxy.service"


def _unit_path() -> Path:
    home = Path(os.environ["HOME"])
    base = (
        Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
        / "systemd"
        / "user"
    )
    return base / _UNIT_NAME


def _render(spec: UserServiceSpec) -> str:
    return (
        "[Unit]\n"
        "Description=piighost anonymizing proxy (user)\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={spec.bin_path} serve --listen-port {spec.listen_port}\n"
        "Restart=on-failure\n"
        "RestartSec=5s\n"
        f"Environment=PIIGHOST_VAULT_DIR={spec.vault_dir}\n"
        f"StandardOutput=append:{spec.log_dir / 'proxy.log'}\n"
        f"StandardError=append:{spec.log_dir / 'proxy.log'}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def install(spec: UserServiceSpec) -> None:
    spec.log_dir.mkdir(parents=True, exist_ok=True)
    unit = _unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(_render(spec), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", _UNIT_NAME], check=True
    )
    user = Path(os.environ["HOME"]).name
    subprocess.run(["loginctl", "enable-linger", user], check=False)


def uninstall(spec: UserServiceSpec) -> None:
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", _UNIT_NAME], check=False
    )
    unit = _unit_path()
    if unit.exists():
        unit.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def status(spec: UserServiceSpec) -> str:
    proc = subprocess.run(
        ["systemctl", "--user", "is-active", _UNIT_NAME],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return "running"
    if "inactive" in proc.stdout:
        return "stopped"
    return "missing"


def restart(spec: UserServiceSpec) -> None:
    subprocess.run(
        ["systemctl", "--user", "restart", _UNIT_NAME], check=True
    )
