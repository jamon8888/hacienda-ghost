"""`piighost proxy` Typer subapp."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from piighost.proxy.handshake import read_handshake

proxy_app = typer.Typer(name="proxy", help="Manage the anonymizing HTTPS proxy")


@proxy_app.command("run")
def run(
    host: Annotated[str, typer.Option(help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port")] = 8443,
    vault: Annotated[Path, typer.Option(help="Vault dir")] = Path.home() / ".piighost",
    cert: Annotated[Path, typer.Option(help="TLS leaf cert")] = Path.home() / ".piighost/proxy/leaf.pem",
    key: Annotated[Path, typer.Option(help="TLS leaf key")] = Path.home() / ".piighost/proxy/leaf.key",
) -> None:
    """Run the proxy in the foreground (debug use)."""
    import asyncio
    import os

    import uvicorn

    from piighost.proxy.handshake import ProxyHandshake, write_handshake
    from piighost.proxy.server import build_app

    async def _run() -> None:
        import secrets

        from piighost.service.core import PIIGhostService
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
            write_handshake(vault, ProxyHandshake(pid=os.getpid(), port=port, token=tok))
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
