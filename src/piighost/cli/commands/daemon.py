"""`piighost daemon start|stop|status|restart|logs`."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from piighost.cli.output import ExitCode, emit_error_line, emit_json_line
from piighost.daemon.lifecycle import ensure_daemon, start_daemon, status, stop_daemon
from piighost.exceptions import VaultNotFound
from piighost.vault.discovery import find_vault_dir

daemon_app = typer.Typer(no_args_is_help=True)


def _vault() -> Path:
    return find_vault_dir(
        start=Path(os.environ.get("PIIGHOST_CWD", Path.cwd()))
    )


def _resolve_or_exit() -> Path:
    try:
        return _vault()
    except VaultNotFound as exc:
        emit_error_line(
            error="VaultNotFound",
            message=str(exc),
            hint="Run `piighost init`",
            exit_code=ExitCode.USER_ERROR,
        )
        raise typer.Exit(code=int(ExitCode.USER_ERROR))


@daemon_app.command("start")
def start_cmd() -> None:
    vault_dir = _resolve_or_exit()
    hs = start_daemon(vault_dir)  # removes daemon.disabled, then ensure_daemon
    emit_json_line(
        {"pid": hs.pid, "port": hs.port, "started_at": hs.started_at}
    )


@daemon_app.command("status")
def status_cmd() -> None:
    vault_dir = _resolve_or_exit()
    hs = status(vault_dir)
    if hs is None:
        emit_json_line({"running": False})
    else:
        emit_json_line({"running": True, "pid": hs.pid, "port": hs.port})


@daemon_app.command("stop")
def stop_cmd() -> None:
    vault_dir = _resolve_or_exit()
    ok = stop_daemon(vault_dir)
    emit_json_line({"stopped": ok})


@daemon_app.command("restart")
def restart_cmd() -> None:
    stop_cmd()
    start_cmd()


@daemon_app.command("logs")
def logs_cmd(tail: int = typer.Option(50, "--tail")) -> None:
    vault_dir = _resolve_or_exit()
    log = vault_dir / "daemon.log"
    if not log.exists():
        emit_json_line({"lines": []})
        return
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
    emit_json_line({"lines": lines})
