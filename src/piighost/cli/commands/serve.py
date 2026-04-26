"""`piighost serve` — run the FastMCP server."""
from __future__ import annotations

import os
from pathlib import Path

import typer

from piighost.cli.commands.vault import _resolve_vault
from piighost.cli.output import ExitCode, emit_error_line
from piighost.exceptions import VaultNotFound


def _resolve_vault_for_serve(explicit: Path | None) -> Path:
    """Resolve vault_dir for `serve`, with env fallbacks for plugin hosts.

    Order:
      1. Explicit ``--vault`` argument.
      2. ``PIIGHOST_VAULT_DIR`` env var (set by ``piighost install`` and
         the MCPB bundles when registering as an MCP server).
      3. ``HACIENDA_DATA_DIR`` env var (set by the hacienda Cowork plugin).
         Both #2 and #3 create the directory on demand —
         ``PIIGhostService.create`` handles migration of a fresh
         directory, so no separate ``piighost init`` is required.
      4. Walk upward from CWD for a ``.piighost/`` marker (standard CLI).
    """
    if explicit is not None:
        return _resolve_vault(explicit)

    for env_name in ("PIIGHOST_VAULT_DIR", "HACIENDA_DATA_DIR"):
        env_dir = os.environ.get(env_name)
        if env_dir:
            path = Path(env_dir).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            return path

    return _resolve_vault(None)


def run(
    vault: Path | None = typer.Option(None, "--vault"),
    transport: str = typer.Option("stdio", "--transport", "-t", help="stdio | sse (mcp transport)"),
) -> None:
    try:
        vault_dir = _resolve_vault_for_serve(vault)
    except VaultNotFound as exc:
        emit_error_line(
            error="VaultNotFound",
            message=str(exc),
            hint="Run `piighost init` here, set PIIGHOST_VAULT_DIR, or pass --vault.",
            exit_code=ExitCode.USER_ERROR,
        )
        raise typer.Exit(code=int(ExitCode.USER_ERROR))

    from piighost.mcp.server import run_mcp
    run_mcp(vault_dir, transport=transport)
