"""Forward-proxy entry point. Run via:

    uv run python -m piighost.proxy.forward --listen-host 127.0.0.1 --listen-port 8443

Production callers should use `piighost proxy run --mode=forward`
(see Task 13) which wraps this entry point with config defaults.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from piighost.proxy.audit import AuditWriter
from piighost.proxy.forward.addon import PiighostAddon
from piighost.proxy.forward.dispatch import build_default_dispatcher


async def _build_service(vault_dir: Path):
    """Construct the anonymization service the handlers depend on.

    Reuses the same service factory that light-mode wires up.
    PIIGHOST_DETECTOR=stub disables GLiNER2 loading for tests.
    """
    from piighost.service.core import PIIGhostService

    return await PIIGhostService.create(vault_dir=vault_dir)


async def build_addon(*, vault_dir: Path) -> PiighostAddon:
    service = await _build_service(vault_dir)
    audit = AuditWriter(root=vault_dir / "audit")
    dispatcher = build_default_dispatcher(service=service, audit=audit)
    return PiighostAddon(dispatcher=dispatcher)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="piighost.proxy.forward")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=8443)
    parser.add_argument("--vault-dir", type=Path, default=Path.home() / ".piighost")
    parser.add_argument(
        "--ca-cert",
        type=Path,
        default=Path.home() / ".piighost" / "proxy" / "ca.pem",
        help="Path to piighost CA cert+key (PEM).",
    )
    return parser.parse_args(argv)


async def _serve(args: argparse.Namespace) -> int:
    from mitmproxy.options import Options
    from mitmproxy.tools.dump import DumpMaster

    opts = Options(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        mode=["regular"],  # forward proxy
        ssl_insecure=False,
        certs=[f"*={args.ca_cert}"],
        # CONNECT to non-Anthropic hosts: tunnel raw, don't decrypt
        ignore_hosts=[
            r"^(?!api\.anthropic\.com).*",
        ],
    )
    master = DumpMaster(opts)
    master.addons.add(await build_addon(vault_dir=args.vault_dir))
    try:
        await master.run()
    except KeyboardInterrupt:
        master.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    return asyncio.run(_serve(args))


if __name__ == "__main__":
    raise SystemExit(main())
