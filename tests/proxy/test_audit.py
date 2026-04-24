from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from piighost.proxy.audit import AuditRecord, AuditWriter


def test_audit_writes_ndjson_line(tmp_path: Path) -> None:
    writer = AuditWriter(root=tmp_path)
    record = AuditRecord(
        ts=datetime(2026, 4, 24, 14, 3, 21, tzinfo=timezone.utc),
        request_id="req_01H",
        project="client-dupont",
        host="claude-code",
        model="claude-opus-4-7",
        entities_detected=[{"label": "PERSON", "count": 2}],
        placeholders_emitted=2,
        request_bytes_in=4821,
        request_bytes_out=4732,
        stream_duration_ms=3421,
        rehydration_errors=0,
        status="ok",
    )
    writer.write(record)

    month_dir = tmp_path / "2026-04"
    file = month_dir / "sessions.ndjson"
    assert file.exists()
    line = json.loads(file.read_text(encoding="utf-8").strip())
    assert line["request_id"] == "req_01H"
    assert line["entities_detected"] == [{"label": "PERSON", "count": 2}]


def test_audit_appends_not_overwrites(tmp_path: Path) -> None:
    writer = AuditWriter(root=tmp_path)
    base = AuditRecord(
        ts=datetime(2026, 4, 24, tzinfo=timezone.utc),
        request_id="r1",
        project="p",
        host="claude-code",
        model="m",
        entities_detected=[],
        placeholders_emitted=0,
        request_bytes_in=0,
        request_bytes_out=0,
        stream_duration_ms=0,
        rehydration_errors=0,
        status="ok",
    )
    writer.write(base)
    writer.write(base.__class__(**{**base.__dict__, "request_id": "r2"}))
    lines = (tmp_path / "2026-04" / "sessions.ndjson").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["request_id"] == "r1"
    assert json.loads(lines[1])["request_id"] == "r2"
