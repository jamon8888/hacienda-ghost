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

__all__ = [
    "DaemonHandshake",
    "StartingMarker",
    "clear_starting_marker",
    "read_handshake",
    "read_starting_marker",
    "write_handshake",
    "write_starting_marker",
]

_HANDSHAKE_FILENAME = "daemon.json"
_STARTING_FILENAME = "daemon.starting"


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


@dataclass(frozen=True)
class StartingMarker:
    """A short-lived marker file that says *"a daemon is mid-startup; don't
    kill it as stale yet."*

    Written by ``__main__.py`` before ``uvicorn.run()`` and cleared by the
    lifespan once eager warm-up completes. Other shims that race past the
    spawn lock (Windows lock files can be flaky under contention) check
    this marker before declaring the existing daemon stale and killing
    it.

    Stored at ``<vault>/daemon.starting`` as JSON: ``{"pid": int, "started_at": int}``.
    """

    pid: int
    started_at: int


def _starting_path(vault_dir: Path) -> Path:
    return vault_dir / _STARTING_FILENAME


def write_starting_marker(vault_dir: Path, marker: StartingMarker) -> None:
    """Atomically write ``marker`` to ``<vault_dir>/daemon.starting``."""
    vault_dir.mkdir(parents=True, exist_ok=True)
    target = _starting_path(vault_dir)
    fd, tmp_name = tempfile.mkstemp(
        prefix="daemon.starting.", suffix=".tmp", dir=str(vault_dir)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(asdict(marker)))
        os.replace(tmp_path, target)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def read_starting_marker(vault_dir: Path) -> StartingMarker | None:
    """Read ``daemon.starting``; return ``None`` if missing or invalid."""
    target = _starting_path(vault_dir)
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    try:
        return StartingMarker(**data)
    except TypeError:
        return None


def clear_starting_marker(vault_dir: Path) -> None:
    """Remove the starting marker. No-op if it doesn't exist."""
    try:
        _starting_path(vault_dir).unlink()
    except FileNotFoundError:
        pass
