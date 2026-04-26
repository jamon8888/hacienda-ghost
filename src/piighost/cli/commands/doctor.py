"""`piighost doctor` — health check across all subsystems."""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Annotated

import typer

from piighost.install.clients import claude_code_settings_path
from piighost.install.host_config import default_settings_path
from piighost.proxy.handshake import read_handshake


def _home() -> Path:
    """Return the home directory, honouring the ``HOME`` env var on all platforms."""
    home_env = os.environ.get("HOME")
    if home_env:
        return Path(home_env)
    return Path.home()


def run(
    vault: Path | None = typer.Option(None, "--vault", help="Vault directory (defaults to ~/.piighost)"),
    probe: Annotated[bool, typer.Option("--probe", help="Live HTTPS interception check against api.anthropic.com")] = False,
) -> None:
    if vault is None:
        vault = _home() / ".piighost"

    failures: list[str] = []

    typer.echo("Checking proxy handshake…")
    hs = read_handshake(vault)
    if hs is None:
        failures.append("proxy: no handshake file (not running)")
    else:
        # Surface mode (active vs paused) so users always know whether their
        # outbound traffic is being anonymized. A "running but paused" daemon
        # behaves like no proxy at all from a privacy standpoint.
        paused = (vault / "paused").exists()
        mode = "paused (transparent passthrough — PII NOT scrubbed)" if paused else "active (anonymizing)"
        typer.echo(f"  ok: pid={hs.pid} port={hs.port} mode={mode}")

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

    typer.echo("Checking hosts file redirect (strict mode)...")
    from piighost.install.hosts_file import has_redirect
    if has_redirect("api.anthropic.com"):
        typer.echo("  ok: api.anthropic.com -> 127.0.0.1")
    else:
        typer.echo("  info: no hosts-file redirect (light mode or strict not installed)")

    if probe:
        _run_probe()

    ok, msg = _check_proxy_reachability()
    if msg:
        typer.echo(msg)
        if not ok:
            raise typer.Exit(code=2)

    if failures:
        typer.echo("")
        typer.echo("FAILURES:")
        for f in failures:
            typer.echo(f"  x {f}")
        raise typer.Exit(code=1)
    typer.echo("\nAll checks passed.")


def _proxy_reachable(host: str = "localhost", port: int = 8443, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_proxy_reachability() -> tuple[bool, str | None]:
    """Returns (ok, message). ok=True if no problem detected.
    The check only runs if the user has BASE_URL configured."""
    settings_path = claude_code_settings_path()
    if not settings_path.exists():
        return True, None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True, None
    base_url = (data.get("env") or {}).get("ANTHROPIC_BASE_URL")
    if not base_url:
        return True, None
    if "localhost:8443" not in base_url and "127.0.0.1:8443" not in base_url:
        return True, None
    if _proxy_reachable():
        return True, None
    return False, (
        "[FAIL] proxy listening on https://localhost:8443\n"
        "       ANTHROPIC_BASE_URL is set in ~/.claude/settings.json,\n"
        "       but :8443 is unreachable. Anthropic API calls from\n"
        "       Claude Code will fail until the proxy is restarted\n"
        "       OR the BASE_URL is removed.\n\n"
        "       Fix options:\n"
        "         1. Start the proxy:    piighost serve &\n"
        "         2. Disconnect:         piighost disconnect\n"
        "         3. Reinstall service:  piighost install --user-service"
    )


def _run_probe() -> None:
    """Live DNS + HTTPS interception check. Informational only (never adds to failures)."""
    import socket
    import httpx

    typer.echo("Probe: checking DNS resolution of api.anthropic.com...")
    try:
        ip = socket.gethostbyname("api.anthropic.com")
        if ip == "127.0.0.1":
            typer.echo(f"  ok: resolves to {ip} (hosts-file redirect active)")
        else:
            typer.echo(f"  warn: resolves to {ip} (not redirected -- hosts-file may not be active)")
    except Exception as exc:
        typer.echo(f"  warn: DNS lookup failed: {exc}")

    typer.echo("Probe: sending HTTPS request to https://api.anthropic.com/piighost-probe...")
    try:
        r = httpx.get("https://api.anthropic.com/piighost-probe", timeout=5.0)
        data = r.json()
        if data.get("intercepted") is True:
            typer.echo("  ok: proxy is intercepting (intercepted=true)")
        else:
            typer.echo(f"  warn: unexpected probe response: {data}")
    except httpx.ConnectError as exc:
        typer.echo(f"  warn: probe failed -- connection refused ({exc}). Is the proxy running?")
    except httpx.SSLError as exc:
        typer.echo(f"  warn: probe failed -- TLS error ({exc}). Is the CA trusted?")
    except Exception as exc:
        typer.echo(f"  warn: probe failed -- {exc}")
