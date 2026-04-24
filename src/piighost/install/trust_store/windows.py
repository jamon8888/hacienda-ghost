"""Windows trust store install via `certutil -addstore Root`.

certutil elevates via UAC if not already elevated.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class TrustStoreError(RuntimeError):
    pass


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise TrustStoreError(f"command failed: {' '.join(cmd)}: {exc}") from exc


def install(ca_path: Path) -> None:
    _run(["certutil", "-addstore", "-f", "Root", str(ca_path)])


def uninstall(ca_path: Path) -> None:
    # certutil identifies certs by serial or subject; -delstore by file is
    # not directly supported. We delete by subject common name.
    _run(["certutil", "-delstore", "Root", "piighost local CA"])
