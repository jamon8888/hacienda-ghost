"""Top-level on/off/status commands for the piighost proxy.

The proxy daemon is meant to run continuously (auto-started by the OS service
manager). Users don't start or stop it for normal operation — they toggle
anonymization with these commands:

    piighost on        anonymize traffic (default)
    piighost off       transparent passthrough — Claude Code goes direct
    piighost status    is it running, and which mode?

Both states keep the daemon process alive, which is what makes strict mode
(hosts file redirect to 127.0.0.1) keep working when the user wants
anonymization off. Toggling is just the creation / removal of a single
flag file at ``<vault>/paused``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from piighost.proxy.handshake import read_handshake

_FLAG = "paused"


def _flag_path(vault: Path) -> Path:
    return vault / _FLAG


def on(
    vault: Annotated[
        Path, typer.Option(help="Vault dir")
    ] = Path.home() / ".piighost",
) -> None:
    """Enable anonymization. Outgoing traffic is PII-scrubbed before reaching Anthropic."""
    flag = _flag_path(vault)
    flag.unlink(missing_ok=True)
    typer.echo("piighost: ON (anonymizing)")


def off(
    vault: Annotated[
        Path, typer.Option(help="Vault dir")
    ] = Path.home() / ".piighost",
) -> None:
    """Pause anonymization. Traffic forwards untouched; the daemon keeps running.

    Use this when you want Claude Code to behave exactly as if the proxy
    weren't installed, without uninstalling or stopping the service.
    """
    flag = _flag_path(vault)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.touch()
    typer.echo("piighost: OFF (paused — transparent passthrough)")


def status(
    vault: Annotated[
        Path, typer.Option(help="Vault dir")
    ] = Path.home() / ".piighost",
) -> None:
    """Report whether the daemon is running, and whether it's anonymizing."""
    hs = read_handshake(vault)
    if hs is None:
        typer.echo("piighost: not running")
        raise typer.Exit(code=1)
    mode = "paused" if _flag_path(vault).exists() else "active"
    typer.echo(f"piighost: running pid={hs.pid} port={hs.port} mode={mode}")
