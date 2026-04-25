# src/piighost/mcp/server.py
"""Thin entry point for ``piighost serve --transport stdio``.

Delegates to the shim, which forwards every tool call to the daemon
on loopback HTTP. The previous in-process FastMCP+PIIGhostService
implementation is gone; the daemon is the single source of truth.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from piighost.mcp.shim import run as _shim_run


def run_mcp(vault_dir: Path, *, transport: str = "stdio") -> None:
    """Run the MCP shim. Only ``transport='stdio'`` is supported.

    The singleton-daemon architecture means SSE transport doesn't make
    sense at the shim layer — the daemon itself is the singleton HTTP
    server. If users need an HTTP-served MCP, they should connect their
    MCP client directly to the daemon's RPC endpoint.
    """
    if transport != "stdio":
        raise NotImplementedError(
            f"transport={transport!r} is not supported by the shim. "
            "Only 'stdio' is available; the daemon's /rpc endpoint is "
            "the only HTTP-served interface in this architecture."
        )
    asyncio.run(_shim_run(vault_dir))
