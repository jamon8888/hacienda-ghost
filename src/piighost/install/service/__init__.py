"""Platform-agnostic background service management for the piighost proxy."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServiceSpec:
    name: str
    bin_path: str
    vault_dir: Path
    cert_path: Path
    key_path: Path
    port: int = 443
    user: str = field(
        default_factory=lambda: os.environ.get("USER") or os.environ.get("USERNAME") or ""
    )


def install_service(spec: ServiceSpec) -> None:
    _dispatch().install(spec)


def uninstall_service(spec: ServiceSpec) -> None:
    _dispatch().uninstall(spec)


def service_running(spec: ServiceSpec) -> bool:
    return _dispatch().running(spec)


def _dispatch():
    if sys.platform == "darwin":
        from piighost.install.service import darwin
        return darwin
    if sys.platform == "win32":
        from piighost.install.service import windows
        return windows
    from piighost.install.service import linux
    return linux
