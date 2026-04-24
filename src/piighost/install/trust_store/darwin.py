"""macOS trust store install via `security add-trusted-cert`.

Adds the root CA to the System keychain with trustRoot policy. Requires
sudo (prompts for admin password once via the GUI).
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
    _run(
        [
            "sudo",
            "security",
            "add-trusted-cert",
            "-d",
            "-r",
            "trustRoot",
            "-k",
            "/Library/Keychains/System.keychain",
            str(ca_path),
        ]
    )


def uninstall(ca_path: Path) -> None:
    _run(
        [
            "sudo",
            "security",
            "remove-trusted-cert",
            "-d",
            str(ca_path),
        ]
    )
