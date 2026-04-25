"""`piighost proxy` Typer subapp."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from piighost.proxy.handshake import read_handshake

proxy_app = typer.Typer(name="proxy", help="Manage the anonymizing HTTPS proxy")


class ProxyMode(str, Enum):
    LIGHT = "light"
    FORWARD = "forward"


@proxy_app.command("run")
def run(
    mode: Annotated[
        ProxyMode,
        typer.Option(
            help="Proxy mode: light (Starlette/uvicorn) or forward (mitmproxy CONNECT)"
        ),
    ] = ProxyMode.LIGHT,
    host: Annotated[str, typer.Option(help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port")] = 8443,
    vault: Annotated[Path, typer.Option(help="Vault dir")] = Path.home() / ".piighost",
    cert: Annotated[
        Path, typer.Option(help="TLS leaf cert (light) or CA cert (forward)")
    ] = Path.home() / ".piighost/proxy/leaf.pem",
    key: Annotated[
        Path, typer.Option(help="TLS leaf key (light mode only)")
    ] = Path.home() / ".piighost/proxy/leaf.key",
) -> None:
    """Run the proxy in the foreground (debug use)."""
    if mode is ProxyMode.FORWARD:
        from piighost.proxy.forward.__main__ import main as forward_main

        argv = [
            "--listen-host",
            host,
            "--listen-port",
            str(port),
            "--vault-dir",
            str(vault),
            "--ca-cert",
            str(cert),
        ]
        raise SystemExit(forward_main(argv))
    import asyncio
    import os

    import uvicorn

    from piighost.proxy.handshake import ProxyHandshake, write_handshake
    from piighost.proxy.server import build_app

    async def _run() -> None:
        import logging
        import secrets

        from piighost.service.core import PIIGhostService

        # Write uvicorn access + error logs to a persistent file so
        # the proxy can be debugged even when running as a background service.
        log_path = vault / "proxy" / "proxy.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            logging.getLogger(name).addHandler(file_handler)

        cfg_path = vault / "config.toml"
        if cfg_path.exists():
            from piighost.service.config import ServiceConfig

            cfg = ServiceConfig.from_toml(cfg_path)
        else:
            from piighost.service.config import ServiceConfig

            cfg = ServiceConfig.default()
        service = await PIIGhostService.create(vault_dir=vault, config=cfg)
        try:
            tok = secrets.token_urlsafe(32)
            write_handshake(
                vault, ProxyHandshake(pid=os.getpid(), port=port, token=tok)
            )
            app_obj = build_app(service=service, vault_dir=vault, token=tok)
            config = uvicorn.Config(
                app_obj,
                host=host,
                port=port,
                ssl_certfile=str(cert),
                ssl_keyfile=str(key),
                log_level="info",
            )
            server = uvicorn.Server(config)
            await server.serve()
        finally:
            await service.close()

    asyncio.run(_run())


@proxy_app.command("status")
def status(
    vault: Annotated[Path, typer.Option()] = Path.home() / ".piighost",
) -> None:
    """Show whether the proxy is running."""
    hs = read_handshake(vault)
    if hs is None:
        typer.echo("proxy: not running")
        raise typer.Exit(code=1)
    typer.echo(f"proxy: running pid={hs.pid} port={hs.port}")


@proxy_app.command("logs")
def logs(
    vault: Annotated[Path, typer.Option(help="Vault dir")] = Path.home() / ".piighost",
    tail: Annotated[
        int, typer.Option("--tail", "-n", help="Last N lines to show")
    ] = 50,
) -> None:
    """Tail the proxy audit log (current month)."""
    import datetime

    now = datetime.datetime.now()
    log_file = vault / "audit" / f"{now.year}-{now.month:02d}" / "sessions.ndjson"
    if not log_file.exists():
        typer.echo(f"No audit log at {log_file}")
        raise typer.Exit(code=1)
    lines = log_file.read_text(encoding="utf-8").splitlines()
    for line in lines[-tail:]:
        typer.echo(line)
