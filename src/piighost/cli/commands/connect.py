"""piighost connect — restore ANTHROPIC_BASE_URL in client config(s)."""
from __future__ import annotations

from typing import Annotated, Optional

import typer

from piighost.install.plan import Client
from piighost.install.recovery import connect


def run(
    client: Annotated[
        Optional[str],
        typer.Option(
            "--client",
            help="Comma-separated client list (code, desktop). Default: all detected.",
        ),
    ] = None,
) -> None:
    """Add ANTHROPIC_BASE_URL=https://localhost:8443 to your Claude
    client(s) so traffic is routed through the local anonymizing proxy.
    Reverses `piighost disconnect`."""
    targets = _parse(client)
    connect(targets)
    typer.echo("Connected. Anthropic API calls now route through the local proxy.")


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
