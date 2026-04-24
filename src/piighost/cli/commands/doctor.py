"""`piighost doctor` — health check across all subsystems."""
from __future__ import annotations

from pathlib import Path

import typer

from piighost.install.host_config import default_settings_path
from piighost.proxy.handshake import read_handshake


def run(vault: Path | None = typer.Option(None, "--vault", help="Vault directory (defaults to ~/.piighost)")) -> None:
    if vault is None:
        vault = Path.home() / ".piighost"

    failures: list[str] = []

    typer.echo("Checking proxy handshake…")
    hs = read_handshake(vault)
    if hs is None:
        failures.append("proxy: no handshake file (not running)")
    else:
        typer.echo(f"  ok: pid={hs.pid} port={hs.port}")

    typer.echo("Checking Claude Code settings.json…")
    settings = default_settings_path()
    if not settings.exists():
        failures.append("claude-code: settings.json missing")
    else:
        import json

        data = json.loads(settings.read_text(encoding="utf-8"))
        base = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
        if not base.startswith("https://localhost"):
            failures.append(
                f"claude-code: ANTHROPIC_BASE_URL not pointed at localhost (got: {base!r})"
            )
        else:
            typer.echo(f"  ok: {base}")

    typer.echo("Checking CA cert on disk…")
    ca = vault / "proxy" / "ca.pem"
    if not ca.exists():
        failures.append(f"ca: missing at {ca}")
    else:
        typer.echo("  ok")

    if failures:
        typer.echo("")
        typer.echo("FAILURES:")
        for f in failures:
            typer.echo(f"  x {f}")
        raise typer.Exit(code=1)
    typer.echo("\nAll checks passed.")
