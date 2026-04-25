"""Structured JSON-line writer for daemon.log."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from piighost.daemon.audit_log import emit


def test_emit_writes_single_json_line(tmp_path: Path) -> None:
    log_path = tmp_path / "daemon.log"
    emit(log_path, "started", pid=1234, port=51207)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["event"] == "started"
    assert obj["pid"] == 1234
    assert obj["port"] == 51207
    assert obj["ts"].endswith("Z")  # UTC ISO 8601


def test_emit_appends_without_clobbering(tmp_path: Path) -> None:
    log_path = tmp_path / "daemon.log"
    emit(log_path, "first", n=1)
    emit(log_path, "second", n=2)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "first"
    assert json.loads(lines[1])["event"] == "second"


def test_emit_creates_parent_dir(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "dir" / "daemon.log"
    emit(log_path, "ok")
    assert log_path.exists()


def test_emit_concurrent_writes_no_corruption(tmp_path: Path) -> None:
    """Two threads emitting in parallel must not produce a torn line."""
    log_path = tmp_path / "daemon.log"

    def hammer(tag: str) -> None:
        for i in range(50):
            emit(log_path, "rpc", tag=tag, i=i)

    t1 = threading.Thread(target=hammer, args=("a",))
    t2 = threading.Thread(target=hammer, args=("b",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 100
    for line in lines:
        json.loads(line)  # must be valid JSON, never a torn row


def test_emit_omits_none_values(tmp_path: Path) -> None:
    log_path = tmp_path / "daemon.log"
    emit(log_path, "rpc", method="anonymize", error=None)
    obj = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "error" not in obj
    assert obj["method"] == "anonymize"
