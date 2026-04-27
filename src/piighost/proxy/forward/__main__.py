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
from typing import Any

from piighost.proxy.audit import AuditWriter
from piighost.proxy.forward.addon import PiighostAddon
from piighost.proxy.forward.dispatch import build_default_dispatcher


class _ServiceAdapter:
    """Adapts PIIGhostService to the _Service protocol expected by handlers.

    PIIGhostService returns rich result objects; MessagesHandler expects
    (anonymized_text, mapping) tuples and plain strings.
    """

    def __init__(self, svc: Any) -> None:
        self._svc = svc

    async def anonymize(self, text: str, *, project: str) -> tuple[str, dict[str, Any]]:
        result = await self._svc.anonymize(text, project=project)
        return result.anonymized, {}

    async def rehydrate(self, text: str, *, project: str) -> str:
        result = await self._svc.rehydrate(text, project=project)
        return result.text

    async def active_project(self) -> str:
        return "default"


async def _build_service(vault_dir: Path) -> _ServiceAdapter:
    """Construct the anonymization service the handlers depend on.

    Reuses the same service factory that light-mode wires up.
    PIIGHOST_DETECTOR=stub disables GLiNER2 loading for tests.
    """
    from piighost.service.core import PIIGhostService

    svc = await PIIGhostService.create(vault_dir=vault_dir)
    return _ServiceAdapter(svc)


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
    import shutil

    from mitmproxy.options import Options
    from mitmproxy.tools.dump import DumpMaster

    # mitmproxy looks for its signing CA as "mitmproxy-ca.pem" inside confdir.
    # Copy our CA there so generated leaf certs are signed by our trusted root.
    ca_dir = args.ca_cert.parent
    ca_dir.mkdir(parents=True, exist_ok=True)
    mitm_ca = ca_dir / "mitmproxy-ca.pem"
    if not mitm_ca.exists():
        shutil.copy2(str(args.ca_cert), str(mitm_ca))

    opts = Options(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        mode=["regular"],  # forward proxy
        ssl_insecure=False,
        confdir=str(ca_dir),
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
