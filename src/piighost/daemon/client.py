"""Thin HTTP client used by the CLI to talk to a running daemon."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from piighost.daemon.handshake import read_handshake

# First-run index calls need to download the embedder model (Solon ~1.1GB) and
# load GLiNER2 (~30-60s on Windows). Steady-state calls complete in ms.
# Override with PIIGHOST_CLIENT_TIMEOUT (seconds).
_DEFAULT_TIMEOUT_SEC = float(os.environ.get("PIIGHOST_CLIENT_TIMEOUT", "900"))


class DaemonClient:
    """Tiny JSON-RPC client that talks to a piighost daemon over loopback."""

    def __init__(self, port: int, token: str) -> None:
        self._base = f"http://127.0.0.1:{port}"
        self._headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def from_vault(cls, vault_dir: Path) -> "DaemonClient | None":
        hs = read_handshake(vault_dir)
        if hs is None:
            return None
        return cls(port=hs.port, token=hs.token)

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        r = httpx.post(
            f"{self._base}/rpc",
            json=body,
            headers=self._headers,
            timeout=_DEFAULT_TIMEOUT_SEC,
        )
        r.raise_for_status()
        payload = r.json()
        if "error" in payload:
            raise RuntimeError(payload["error"]["message"])
        return payload["result"]
