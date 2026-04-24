"""Handshake file for discovering the running proxy.

Mirrors daemon/handshake.py but with its own file so a daemon and proxy
can coexist.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = ["ProxyHandshake", "read_handshake", "write_handshake"]

_FILE = "proxy.handshake.json"


@dataclass
class ProxyHandshake:
    """Serialized proxy connection info written to ``<vault>/proxy.handshake.json``."""

    pid: int
    port: int
    token: str


def write_handshake(vault_dir: Path, hs: ProxyHandshake) -> None:
    """Atomically write ``hs`` to ``<vault_dir>/proxy.handshake.json``.

    Writes go to a temp file in ``vault_dir`` (same filesystem) and are
    then renamed into place with :func:`os.replace`, which is atomic on
    POSIX and Windows.
    """
    vault_dir.mkdir(parents=True, exist_ok=True)
    tmp = vault_dir / (_FILE + ".tmp")
    tmp.write_text(json.dumps(asdict(hs)), encoding="utf-8")
    os.replace(tmp, vault_dir / _FILE)


def read_handshake(vault_dir: Path) -> ProxyHandshake | None:
    """Read the handshake file, or return ``None`` if missing."""
    path = vault_dir / _FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return ProxyHandshake(**data)
