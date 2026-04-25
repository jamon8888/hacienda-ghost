"""Single-writer JSON-Lines logger for the piighost daemon.log file.

Why a custom writer:
  - Strict format (one JSON object per line, no logging-module overhead)
  - Atomic append: a single ``write()`` syscall per line, so concurrent
    writers never tear a line. We open with ``O_APPEND`` so the kernel
    serializes appends across *processes*. A per-path threading lock
    covers concurrent threads within the same process (needed on Windows
    where O_APPEND does not guarantee intra-process atomicity).
  - UTC ISO 8601 timestamps with explicit ``Z`` suffix (no ambiguity).
  - None-valued fields are omitted to keep lines compact.

Usage:
    emit(vault_dir / "daemon.log", "rpc", method="anonymize",
         duration_ms=42, status="ok")
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Per-path locks: serialise threads writing to the same file within one process.
# Different file paths get independent locks so unrelated log files don't block
# each other. Cross-process safety is still provided by O_APPEND.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _get_lock(path: str) -> threading.Lock:
    with _locks_guard:
        if path not in _locks:
            _locks[path] = threading.Lock()
        return _locks[path]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(log_path: Path, event: str, **fields: Any) -> None:
    """Append one JSON line to ``log_path``.

    ``fields`` whose value is ``None`` are dropped. The line ends with
    a single ``\\n``.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"ts": _now_iso(), "event": event}
    for k, v in fields.items():
        if v is not None:
            payload[k] = v
    line = json.dumps(payload, default=str) + "\n"
    encoded = line.encode("utf-8")
    lock = _get_lock(str(log_path.resolve()))
    with lock:
        fd = os.open(str(log_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)
