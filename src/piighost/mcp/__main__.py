"""Direct MCP server entry point — bypasses the full piighost CLI.

Run with::

    python -m piighost.mcp [--vault PATH]

Used by Claude Desktop / Claude Code MCP configs to avoid the
~18-second cold-start penalty of importing the entire ``piighost.cli``
surface (which eagerly loads index, query, daemon, proxy, install
command modules and their heavy transitive deps like kreuzberg,
lancedb, mitmproxy).

This entry point imports only what's strictly needed to serve MCP:
the shim + daemon lifecycle helpers. Tool dispatch lazily spawns
the daemon on first call, so initialize/tools/list complete in
under 3 seconds on Windows.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def _resolve_vault_dir(explicit: str | None) -> Path:
    """Locate the vault dir from --vault, env vars, or default."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    for env_name in ("PIIGHOST_VAULT_DIR", "HACIENDA_DATA_DIR"):
        env_dir = os.environ.get(env_name)
        if env_dir:
            return Path(env_dir).expanduser().resolve()
    return Path.home() / ".piighost" / "vault"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m piighost.mcp",
        description="piighost MCP server (stdio transport).",
    )
    parser.add_argument(
        "--vault",
        default=None,
        help="Vault directory. Falls back to PIIGHOST_VAULT_DIR / "
             "HACIENDA_DATA_DIR env vars, then ~/.piighost/vault.",
    )
    args = parser.parse_args(argv)

    vault_dir = _resolve_vault_dir(args.vault)
    vault_dir.mkdir(parents=True, exist_ok=True)

    from piighost.mcp.shim import run as _shim_run
    asyncio.run(_shim_run(vault_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
