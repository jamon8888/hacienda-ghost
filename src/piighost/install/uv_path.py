from __future__ import annotations

import shutil
import subprocess


class UvNotFoundError(RuntimeError):
    pass


def ensure_uv() -> str:
    path = shutil.which("uv")
    if path is None:
        raise UvNotFoundError(
            "uv not found on PATH. Install from https://astral.sh/uv "
            "or run: pip install uv"
        )
    return path


def install_piighost(*, uv_path: str, dry_run: bool) -> None:
    if dry_run:
        return
    cmd = [
        uv_path, "tool", "install",
        "piighost[mcp,index,gliner2]",
        "--python", "3.12",
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"uv tool install failed (exit {exc.returncode}). "
            f'Fallback: pip install "piighost[mcp,index,gliner2]"'
        ) from exc
