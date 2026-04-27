"""Append-only JSONL audit log for sensitive vault operations."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    """Versioned audit event (v2). Append-only.

    The hash chain (``prev_hash`` / ``event_hash``) is recorded
    eagerly here so a future forensic-verification subsystem can
    detect tampering without a schema migration. Verification itself
    is **not** in Phase 0 scope.
    """

    v: Literal[2] = 2
    event_id: str
    event_type: str
    timestamp: float
    actor: str = "user"
    project_id: str = ""
    subject_token: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str | None = None
    event_hash: str


def _canonicalize_for_hash(payload: dict[str, Any]) -> str:
    """Stable JSON serialization for hashing — sort_keys + tight separators."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _compute_event_hash(payload_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonicalize_for_hash(payload_without_hash).encode("utf-8")
    ).hexdigest()


def parse_event_line(line: str) -> AuditEvent | None:
    """Parse one audit-log line into an AuditEvent (v2).

    Recognises:
      - native v2 rows (``{"v": 2, ...}``)
      - legacy v1 rows (``{"ts", "op", "token", "caller_kind", ...}``)
        — synthesized into v2 with a generated ``event_id`` and
        ``event_hash``. ``prev_hash`` is left None for legacy rows
        because the chain wasn't tracked at write-time.

    Returns None on JSON errors or unknown shapes.
    """
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    v = raw.get("v")
    if v == 2:
        try:
            return AuditEvent.model_validate(raw)
        except Exception:
            return None
    # Legacy v1: {"ts", "op", "token", "caller_kind", "caller_pid", "metadata"}
    if "op" in raw and ("ts" in raw or "timestamp" in raw):
        ts = raw.get("ts") or raw.get("timestamp") or 0
        synth_payload: dict[str, Any] = {
            "v": 2,
            "event_id": uuid.uuid4().hex,
            "event_type": raw["op"],
            "timestamp": float(ts),
            "actor": "user",
            "project_id": raw.get("project_id", ""),
            "subject_token": raw.get("token"),
            "metadata": {
                "caller_kind": raw.get("caller_kind"),
                "caller_pid": raw.get("caller_pid"),
                **(raw.get("metadata") or {}),
            },
            "prev_hash": None,
        }
        synth_payload["event_hash"] = _compute_event_hash(synth_payload)
        try:
            return AuditEvent.model_validate(synth_payload)
        except Exception:
            return None
    return None


def read_events(path: Path) -> Iterator[AuditEvent]:
    """Stream events from an audit.log file, lifting v1 rows to v2.

    Skips blank lines and garbage. Yields in file order (chronological
    if the writer is append-only, which AuditLogger guarantees).
    """
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            ev = parse_event_line(line)
            if ev is not None:
                yield ev


class AuditLogger:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        op: str,
        token: str | None = None,
        caller_kind: str = "cli",
        caller_pid: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        row = {
            "ts": int(time.time()),
            "op": op,
            "token": token,
            "caller_kind": caller_kind,
            "caller_pid": caller_pid,
            "metadata": metadata or {},
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def record_v2(
        self,
        *,
        event_type: str,
        project_id: str = "",
        actor: str = "user",
        subject_token: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Append one v2 event with hash chain. Returns the event.

        ``prev_hash`` is computed by reading the last v2 event from
        disk. For the first v2 event in a fresh log, ``prev_hash`` is
        None.
        """
        prev_hash = self._last_event_hash()
        payload: dict[str, Any] = {
            "v": 2,
            "event_id": uuid.uuid4().hex,
            "event_type": event_type,
            "timestamp": time.time(),
            "actor": actor,
            "project_id": project_id,
            "subject_token": subject_token,
            "metadata": dict(metadata or {}),
            "prev_hash": prev_hash,
        }
        payload["event_hash"] = _compute_event_hash(payload)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return AuditEvent.model_validate(payload)

    def _last_event_hash(self) -> str | None:
        """Return the event_hash of the last v2 line, or None."""
        if not self._path.exists():
            return None
        last_v2_hash: str | None = None
        with self._path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                ev = parse_event_line(line)
                if ev is not None:
                    last_v2_hash = ev.event_hash
        return last_v2_hash
