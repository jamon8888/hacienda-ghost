"""`piighost cleanup` — remove stale handshake/lock files, kill orphans."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Annotated

import psutil
import typer

from piighost.daemon import reaper


def _is_pid_alive(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def _scan_stale_state_files(vault: Path) -> list[Path]:
    """Find handshake/lock files whose recorded PID is dead."""
    stale: list[Path] = []
    candidates = (
        list(vault.glob("*.json"))
        + list(vault.glob("*.lock"))
        + list(vault.glob("*.handshake.json"))
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = data.get("pid")
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        if isinstance(pid, int) and pid > 0 and not _is_pid_alive(pid):
            stale.append(path)
    return stale


def _check_disabled_flag_age(vault: Path) -> str | None:
    """Return a warning if daemon.disabled exists without a matching log entry."""
    flag = vault / "daemon.disabled"
    if not flag.exists():
        return None
    log_path = vault / "daemon.log"
    if not log_path.exists():
        return "daemon.disabled present but no daemon.log to verify recent stop"
    for line in reversed(log_path.read_text(encoding="utf-8").splitlines()[-100:]):
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("event") == "daemon_stopped":
            return None
    return "daemon.disabled present but no recent daemon_stopped event in log"


def run(
    vault: Annotated[Path, typer.Option(help="Vault dir")] = Path.home() / ".piighost",
    force: Annotated[bool, typer.Option("--force", help="Apply changes (default: dry-run)")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
) -> None:
    """Reap orphan piighost serve processes and stale state files."""
    vault = Path(vault)
    actions: dict[str, list] = {"removed": [], "killed": [], "warnings": []}

    # 1. Stale state files
    for path in _scan_stale_state_files(vault):
        if force:
            try:
                path.unlink()
                actions["removed"].append(str(path))
            except OSError as exc:
                actions["warnings"].append(f"could not remove {path}: {exc}")
        else:
            actions["removed"].append(f"[would remove] {path}")

    # 2. Orphan shims
    if force:
        actions["killed"] = reaper.reap()
    else:
        # Dry-run: report what reaper.reap() would touch without killing.
        from piighost.daemon.reaper import _iter_serves, _is_orphan  # noqa: PLC0415

        actions["killed"] = [
            f"[would kill] pid={p.pid}" for p in _iter_serves() if _is_orphan(p)
        ]

    # 3. Disabled flag sanity check
    warn = _check_disabled_flag_age(vault)
    if warn:
        actions["warnings"].append(warn)

    if json_out:
        typer.echo(json.dumps(actions, indent=2))
        return

    if actions["removed"]:
        for r in actions["removed"]:
            typer.echo(f"[stale] {r}")
    if actions["killed"]:
        for k in actions["killed"]:
            typer.echo(f"[orphan] {k}")
    if actions["warnings"]:
        for w in actions["warnings"]:
            typer.echo(f"[warn] {w}")
    if not any(actions.values()):
        typer.echo("nothing to clean")

    if not force:
        typer.echo("\n(dry-run — pass --force to apply)")
