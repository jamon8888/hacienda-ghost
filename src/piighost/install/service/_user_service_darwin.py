"""LaunchAgent backend (macOS) for piighost proxy auto-restart."""
from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from piighost.install.service.user_service import UserServiceSpec


def _plist_path(spec: UserServiceSpec) -> Path:
    home = Path(os.environ["HOME"])
    return home / "Library" / "LaunchAgents" / f"{spec.name}.plist"


def _render(spec: UserServiceSpec) -> bytes:
    payload = {
        "Label": spec.name,
        "ProgramArguments": [
            str(spec.bin_path),
            "serve",
            "--listen-port",
            str(spec.listen_port),
        ],
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "RunAtLoad": True,
        "StandardOutPath": str(spec.log_dir / "proxy.log"),
        "StandardErrorPath": str(spec.log_dir / "proxy.log"),
        "EnvironmentVariables": {
            "PIIGHOST_VAULT_DIR": str(spec.vault_dir),
        },
    }
    return plistlib.dumps(payload)


def install(spec: UserServiceSpec) -> None:
    spec.log_dir.mkdir(parents=True, exist_ok=True)
    plist = _plist_path(spec)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(_render(spec))
    subprocess.run(["launchctl", "load", "-w", str(plist)], check=True)


def uninstall(spec: UserServiceSpec) -> None:
    plist = _plist_path(spec)
    if plist.exists():
        subprocess.run(
            ["launchctl", "unload", "-w", str(plist)], check=False
        )
        plist.unlink()


def status(spec: UserServiceSpec) -> str:
    proc = subprocess.run(
        ["launchctl", "list", spec.name], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return "missing"
    # Output format: "<pid>\t<status>\t<label>"
    first = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
    pid_field = first.split("\t", 1)[0] if first else "-"
    return "running" if pid_field.isdigit() else "stopped"


def restart(spec: UserServiceSpec) -> None:
    plist = _plist_path(spec)
    subprocess.run(["launchctl", "unload", "-w", str(plist)], check=False)
    subprocess.run(["launchctl", "load", "-w", str(plist)], check=True)
