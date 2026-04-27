"""Tests for AuditEvent v2 + record_v2 + v1->v2 reader."""
from __future__ import annotations

import json

from piighost.vault.audit import (
    AuditEvent, AuditLogger, parse_event_line, read_events,
)


def test_audit_event_v2_round_trip():
    ev = AuditEvent(
        event_id="abc12345",
        event_type="query",
        timestamp=1777000000.0,
        actor="alice",
        project_id="p1",
        subject_token=None,
        metadata={"foo": "bar"},
        prev_hash=None,
        event_hash="zzz",
    )
    raw = ev.model_dump_json()
    parsed = AuditEvent.model_validate_json(raw)
    assert parsed.v == 2
    assert parsed.event_type == "query"
    assert parsed.metadata == {"foo": "bar"}


def test_record_v2_writes_v2_with_hash_chain(tmp_path):
    log = AuditLogger(tmp_path / "audit.log")
    log.record_v2(event_type="query", project_id="p1", metadata={"k": "v"})
    log.record_v2(event_type="anonymize", project_id="p1")

    lines = (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    e1 = json.loads(lines[0])
    e2 = json.loads(lines[1])
    assert e1["v"] == 2
    assert e1["prev_hash"] is None
    assert e2["v"] == 2
    assert e2["prev_hash"] == e1["event_hash"]
    assert e1["event_hash"] != e2["event_hash"]


def test_parse_event_line_recognises_v2():
    line = json.dumps({
        "v": 2, "event_id": "abc", "event_type": "query",
        "timestamp": 1700000000.0, "actor": "u", "project_id": "p",
        "subject_token": None, "metadata": {}, "prev_hash": None,
        "event_hash": "deadbeef",
    })
    ev = parse_event_line(line)
    assert ev is not None
    assert ev.v == 2
    assert ev.event_type == "query"


def test_parse_event_line_synthesizes_v2_from_v1():
    """Legacy v1 row {op, token, caller_kind, ts} must be lifted to v2."""
    line = json.dumps({
        "ts": 1700000000,
        "op": "rehydrate",
        "token": "<<nom_personne:abc>>",
        "caller_kind": "service",
        "caller_pid": 1234,
        "metadata": {},
    })
    ev = parse_event_line(line)
    assert ev is not None
    assert ev.v == 2  # synthesized
    assert ev.event_type == "rehydrate"
    assert ev.timestamp == 1700000000.0
    assert ev.subject_token == "<<nom_personne:abc>>"
    assert ev.metadata.get("caller_kind") == "service"
    assert ev.event_id  # generated
    assert ev.event_hash  # synthesized


def test_parse_event_line_returns_none_on_garbage():
    assert parse_event_line("not json") is None
    assert parse_event_line('{"unknown_format": true}') is None


def test_read_events_handles_mixed_v1_v2(tmp_path):
    path = tmp_path / "audit.log"
    v1_row = json.dumps({"ts": 1700000000, "op": "query", "token": None, "caller_kind": "skill", "caller_pid": None, "metadata": {}})
    v2_row = json.dumps({
        "v": 2, "event_id": "id2", "event_type": "anonymize",
        "timestamp": 1700000001.0, "actor": "u", "project_id": "p",
        "subject_token": None, "metadata": {}, "prev_hash": None,
        "event_hash": "hash2",
    })
    path.write_text(v1_row + "\n" + v2_row + "\n", encoding="utf-8")

    events = list(read_events(path))
    assert len(events) == 2
    assert events[0].event_type == "query"
    assert events[1].event_type == "anonymize"
    assert all(e.v == 2 for e in events)


def test_read_events_skips_blank_lines_and_garbage(tmp_path):
    path = tmp_path / "audit.log"
    v2_row = json.dumps({
        "v": 2, "event_id": "id", "event_type": "query",
        "timestamp": 1700000000.0, "actor": "u", "project_id": "p",
        "subject_token": None, "metadata": {}, "prev_hash": None,
        "event_hash": "h",
    })
    path.write_text(v2_row + "\n\nnot-json\n" + v2_row + "\n", encoding="utf-8")
    events = list(read_events(path))
    assert len(events) == 2


def test_record_v2_preserves_existing_v1_writer(tmp_path):
    """Verify the legacy AuditLogger.record() still works (no v2 hijack)."""
    log = AuditLogger(tmp_path / "audit.log")
    log.record(op="query", token="<<x:abc>>", caller_kind="cli")
    log.record_v2(event_type="anonymize", project_id="p")
    events = list(read_events(tmp_path / "audit.log"))
    assert len(events) == 2
    assert events[0].event_type == "query"  # v1 lifted to v2
    assert events[1].event_type == "anonymize"  # native v2
