"""piighost connect / disconnect — toggle ANTHROPIC_BASE_URL in
client configs without touching the MCP server registration.

Both commands are stateless: they rewrite JSON. They work whether
the proxy daemon is running, stopped, or completely uninstalled.
"""
from __future__ import annotations

from piighost.install.clients import (
    detect_all,
    claude_code_settings_path,
    read_config,
    write_config,
)
from piighost.install.plan import Client


_PROXY_BASE_URL = "https://localhost:8443"


def connect(clients: frozenset[Client] | None = None) -> None:
    """Re-add ANTHROPIC_BASE_URL=https://localhost:8443 to the named
    Claude Code config. (Claude Desktop doesn't honour env there.)
    Default: all detected clients."""
    targets = _resolve(clients)
    for client in targets:
        if client is not Client.CLAUDE_CODE:
            continue  # only Claude Code uses the env var
        path = claude_code_settings_path()
        if not path.exists():
            continue
        config = read_config(path)
        config.setdefault("env", {})["ANTHROPIC_BASE_URL"] = _PROXY_BASE_URL
        write_config(path, config)


def disconnect(clients: frozenset[Client] | None = None) -> None:
    """Remove ANTHROPIC_BASE_URL from the named clients' configs.
    Default: all detected clients. Leaves MCP server registration intact."""
    targets = _resolve(clients)
    for client in targets:
        if client is not Client.CLAUDE_CODE:
            continue
        path = claude_code_settings_path()
        if not path.exists():
            continue
        config = read_config(path)
        env = config.get("env") or {}
        env.pop("ANTHROPIC_BASE_URL", None)
        if env:
            config["env"] = env
        else:
            config.pop("env", None)
        write_config(path, config)


def _resolve(clients: frozenset[Client] | None) -> frozenset[Client]:
    if clients is not None:
        return clients
    return frozenset(loc.client for loc in detect_all() if loc.exists)
