"""Atomic read/write of the ``daemon.json`` handshake file.

The handshake file lives inside the vault directory and advertises how to
reach a running piighost daemon (PID, local HTTP port, auth token, start
time). Writes are atomic: we write to a temp file in the same directory
and then ``os.replace`` it into place so a concurrent reader either sees
the old contents or the new ones, never a half-written file.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = ["DaemonHandshake", "read_handshake", "write_handshake"]

_HANDSHAKE_FILENAME = "daemon.json"


@dataclass(frozen=True)
class DaemonHandshake:
    """Serialized daemon connection info written to ``<vault>/daemon.json``."""

    pid: int
    port: int
    token: str
    started_at: int


def _handshake_path(vault_dir: Path) -> Path:
    return vault_dir / _HANDSHAKE_FILENAME


def write_handshake(vault_dir: Path, hs: DaemonHandshake) -> None:
    """Atomically write ``hs`` to ``<vault_dir>/daemon.json``.

    Writes go to a temp file in ``vault_dir`` (same filesystem) and are
    then renamed into place with :func:`os.replace`, which is atomic on
    POSIX and Windows. On failure the temp file is unlinked.
    """

    vault_dir.mkdir(parents=True, exist_ok=True)
    target = _handshake_path(vault_dir)

    fd, tmp_name = tempfile.mkstemp(
        prefix="daemon.", suffix=".json", dir=str(vault_dir)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(asdict(hs)))
        os.replace(tmp_path, target)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def read_handshake(vault_dir: Path) -> DaemonHandshake | None:
    """Read the handshake file, or return ``None`` if missing/invalid."""

    target = _handshake_path(vault_dir)
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    try:
        return DaemonHandshake(**data)
    except TypeError:
        return None
