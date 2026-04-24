"""Linux trust store install.

Debian/Ubuntu: copy to /usr/local/share/ca-certificates/ + update-ca-certificates.
Fedora/RHEL:    trust anchor <pem>.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_DEBIAN_DIR = Path("/usr/local/share/ca-certificates")
_CRT_NAME = "piighost.crt"


class TrustStoreError(RuntimeError):
    pass


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise TrustStoreError(f"command failed: {' '.join(cmd)}: {exc}") from exc


def _detect_family() -> str:
    if shutil.which("update-ca-certificates"):
        return "debian"
    if shutil.which("trust"):
        return "fedora"
    return "unknown"


def install(ca_path: Path) -> None:
    family = _detect_family()
    if family == "debian":
        target = _DEBIAN_DIR / _CRT_NAME
        _run(["sudo", "cp", str(ca_path), str(target)])
        _run(["sudo", "update-ca-certificates"])
    elif family == "fedora":
        _run(["sudo", "trust", "anchor", str(ca_path)])
    else:
        raise TrustStoreError(
            "No known CA trust tool (update-ca-certificates or trust) found."
        )


def uninstall(ca_path: Path) -> None:
    family = _detect_family()
    if family == "debian":
        target = _DEBIAN_DIR / _CRT_NAME
        _run(["sudo", "rm", "-f", str(target)])
        _run(["sudo", "update-ca-certificates", "--fresh"])
    elif family == "fedora":
        _run(["sudo", "trust", "anchor", "--remove", str(ca_path)])
    else:
        raise TrustStoreError(
            "No known CA trust tool found for uninstall."
        )
