"""piighost disconnect — remove ANTHROPIC_BASE_URL from client config(s)."""
from __future__ import annotations

from typing import Annotated, Optional

import typer

from piighost.install.plan import Client
from piighost.install.recovery import disconnect


def run(
    client: Annotated[
        Optional[str],
        typer.Option(
            "--client",
            help="Comma-separated client list (code, desktop). Default: all detected.",
        ),
    ] = None,
) -> None:
    """Remove ANTHROPIC_BASE_URL from Claude Code's settings.json so
    Anthropic API calls go direct again. (Claude Desktop is unaffected;
    it never uses the env var.) The MCP server registration is preserved
    — disconnecting only stops proxy interception, leaves your tools
    available."""
    targets = _parse(client)
    disconnect(targets)
    typer.echo("Disconnected. Anthropic API calls go directly to api.anthropic.com.")


def _parse(raw: str | None) -> frozenset[Client] | None:
    if raw is None:
        return None
    out: set[Client] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if tok == "code":
            out.add(Client.CLAUDE_CODE)
        elif tok == "desktop":
            out.add(Client.CLAUDE_DESKTOP)
        else:
            raise typer.BadParameter(
                f"unknown client {tok!r}. Valid: code, desktop."
            )
    return frozenset(out)
