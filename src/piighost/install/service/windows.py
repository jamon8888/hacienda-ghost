# src/piighost/install/service/windows.py
"""Windows scheduled task + netsh urlacl install for piighost proxy."""
from __future__ import annotations

import os
import subprocess

from piighost.install.service import ServiceSpec

_TASK_NAME = "piighost-proxy"


def _urlacl_url(spec: ServiceSpec) -> str:
    return f"https://127.0.0.1:{spec.port}/"


def install(spec: ServiceSpec) -> None:
    url = _urlacl_url(spec)
    username = os.environ.get("USERNAME") or spec.user
    subprocess.run(
        ["netsh", "http", "add", "urlacl", f"url={url}", f"user={username}"],
        check=True,
    )
    # schtasks requires a single /tr string, not a list.
    tr_cmd = (
        f'"{spec.bin_path}" proxy run'
        f" --port {spec.port}"
        f' --vault "{spec.vault_dir}"'
        f' --cert "{spec.cert_path}"'
        f' --key "{spec.key_path}"'
    )
    subprocess.run(
        [
            "schtasks", "/create",
            "/tn", _TASK_NAME,
            "/sc", "ONLOGON",
            "/rl", "HIGHEST",
            "/tr", tr_cmd,
            "/f",
        ],
        check=True,
    )


def uninstall(spec: ServiceSpec) -> None:
    subprocess.run(["schtasks", "/delete", "/tn", _TASK_NAME, "/f"], check=False)
    url = _urlacl_url(spec)
    subprocess.run(["netsh", "http", "delete", "urlacl", f"url={url}"], check=False)


def running(spec: ServiceSpec) -> bool:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", _TASK_NAME, "/fo", "LIST"],
        capture_output=True,
    )
    if result.returncode != 0:
        return False
    return b"Running" in result.stdout
