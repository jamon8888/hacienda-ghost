"""Per-platform user-level (no-admin) auto-restart service for the
piighost proxy daemon.

Each platform gets a thin module dispatched on import: macOS uses
LaunchAgent (KeepAlive=true), Linux uses systemd --user, Windows
uses a Scheduled Task with /onlogon trigger.

The Windows path is best-effort — Windows lacks a native unprivileged
KeepAlive analogue. We document the gap rather than paper over it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class UserServiceSpec:
    name: str
    bin_path: Path
    vault_dir: Path
    log_dir: Path
    listen_port: int


# ---- public API ---------------------------------------------------------

def install(spec: UserServiceSpec) -> None:
    _backend().install(spec)


def uninstall(spec: UserServiceSpec) -> None:
    _backend().uninstall(spec)


def status(spec: UserServiceSpec) -> Literal["running", "stopped", "missing"]:
    return _backend().status(spec)


def restart(spec: UserServiceSpec) -> None:
    _backend().restart(spec)


# ---- backend dispatch ---------------------------------------------------

def _backend():
    if sys.platform == "darwin":
        from piighost.install.service import _user_service_darwin
        return _user_service_darwin
    if sys.platform == "win32":
        from piighost.install.service import _user_service_windows
        return _user_service_windows
    from piighost.install.service import _user_service_linux
    return _user_service_linux
