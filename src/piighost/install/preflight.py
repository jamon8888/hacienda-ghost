from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path


class PreflightError(RuntimeError):
    pass


def check_disk_space(min_gb: float = 2.0) -> None:
    usage = shutil.disk_usage(Path.home())
    free_gb = usage.free / 1024**3
    if free_gb < min_gb:
        raise PreflightError(
            f"Insufficient disk space: {free_gb:.1f} GB free, {min_gb:.1f} GB required. "
            f"Pass --force to proceed anyway."
        )


def check_internet() -> None:
    try:
        with urllib.request.urlopen("https://pypi.org", timeout=5):
            pass
    except OSError as exc:
        raise PreflightError(
            f"No internet access: {exc}. "
            f"Check your connection or set HTTPS_PROXY."
        ) from exc


def check_python_version() -> None:
    if sys.version_info < (3, 12):
        raise PreflightError(
            f"Python 3.12+ required (found {sys.version_info[0]}.{sys.version_info[1]}). "
            f"Run: uv python install 3.12"
        )
