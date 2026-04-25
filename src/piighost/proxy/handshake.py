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


def _pid_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` exists on this host.

    Uses psutil, which is a hard dependency of the package. Any failure
    (psutil missing, permission errors, etc.) errs on the side of
    "alive" so we never wrongly delete a valid handshake.
    """
    if pid <= 0:
        return False
    try:
        import psutil  # type: ignore[import-not-found]
        return psutil.pid_exists(pid)
    except Exception:
        return True


def read_handshake(vault_dir: Path) -> ProxyHandshake | None:
    """Read the handshake file, or return ``None`` if missing or stale.

    A handshake is *stale* when the recorded PID is no longer running —
    typically because the proxy was killed with SIGKILL or the host
    rebooted before the daemon could clean up. In that case the handshake
    file is removed so callers (``piighost status``, ``piighost doctor``,
    etc.) stop reporting phantom state.
    """
    path = vault_dir / _FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        hs = ProxyHandshake(**data)
    except Exception:
        # Corrupt file — treat as absent and clean it up.
        path.unlink(missing_ok=True)
        return None

    if not _pid_alive(hs.pid):
        path.unlink(missing_ok=True)
        return None
    return hs
