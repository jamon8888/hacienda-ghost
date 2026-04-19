"""CLI entry point. Commands are registered by later tasks."""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False, help="piighost — GDPR-compliant PII anonymization CLI")


@app.command(hidden=True)
def _placeholder() -> None:
    """Placeholder command so typer has a valid invocation target.

    Real commands are registered by later Sprint 1 tasks (init, daemon, client).
    """
    typer.echo("piighost CLI scaffold — no commands registered yet.")
