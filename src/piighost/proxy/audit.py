"""Per-request NDJSON audit writer. See spec §6.1."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class AuditRecord:
    ts: datetime
    request_id: str
    project: str
    host: str
    model: str
    entities_detected: list[dict[str, Any]]
    placeholders_emitted: int
    request_bytes_in: int
    request_bytes_out: int
    stream_duration_ms: int
    rehydration_errors: int
    status: str


class AuditWriter:
    def __init__(self, *, root: Path) -> None:
        self._root = root

    def write(self, record: AuditRecord) -> None:
        month = record.ts.strftime("%Y-%m")
        month_dir = self._root / month
        month_dir.mkdir(parents=True, exist_ok=True)
        file = month_dir / "sessions.ndjson"
        data = asdict(record)
        data["ts"] = record.ts.isoformat()
        with file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
