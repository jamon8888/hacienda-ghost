"""schtasks /onlogon backend (Windows) for piighost proxy auto-restart.

Windows has no native unprivileged equivalent of LaunchAgent's
KeepAlive — the Scheduled Task only fires at logon. If the daemon
crashes mid-session, it will not be restarted until the next logon.
We document this in docs/install-paths.md and recommend running
`piighost serve` from a terminal for long-lived dev sessions, or
using strict mode (with admin) when uptime matters.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from piighost.install.service.user_service import UserServiceSpec


def _task_name(spec: UserServiceSpec) -> str:
    return r"\piighost\proxy"


def _schtasks() -> str:
    return os.path.join(os.environ["SystemRoot"], "System32", "schtasks.exe")


def install(spec: UserServiceSpec) -> None:
    spec.log_dir.mkdir(parents=True, exist_ok=True)
    cmd = (
        f'"{spec.bin_path}" serve --listen-port {spec.listen_port}'
    )
    subprocess.run(
        [
            _schtasks(),
            "/create",
            "/tn", _task_name(spec),
            "/tr", cmd,
            "/sc", "onlogon",
            "/rl", "limited",
            "/f",  # overwrite if exists
        ],
        check=True,
    )


def uninstall(spec: UserServiceSpec) -> None:
    subprocess.run(
        [_schtasks(), "/delete", "/tn", _task_name(spec), "/f"],
        check=False,
    )


def status(spec: UserServiceSpec) -> str:
    proc = subprocess.run(
        [_schtasks(), "/query", "/tn", _task_name(spec), "/v", "/fo", "list"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return "missing"
    if "Running" in proc.stdout:
        return "running"
    return "stopped"


def restart(spec: UserServiceSpec) -> None:
    subprocess.run(
        [_schtasks(), "/end", "/tn", _task_name(spec)], check=False
    )
    subprocess.run(
        [_schtasks(), "/run", "/tn", _task_name(spec)], check=True
    )
