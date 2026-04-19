"""Tests for atomic daemon.json handshake file."""

from __future__ import annotations

from pathlib import Path

from piighost.daemon import DaemonHandshake, read_handshake, write_handshake


def test_write_then_read(tmp_path: Path) -> None:
    hs = DaemonHandshake(pid=1234, port=50001, token="abc", started_at=42)
    write_handshake(tmp_path, hs)

    got = read_handshake(tmp_path)
    assert got == hs


def test_read_missing_returns_none(tmp_path: Path) -> None:
    # No daemon.json written yet.
    assert read_handshake(tmp_path) is None


def test_write_is_atomic(tmp_path: Path) -> None:
    first = DaemonHandshake(pid=1, port=50001, token="t1", started_at=10)
    second = DaemonHandshake(pid=2, port=50002, token="t2", started_at=20)

    write_handshake(tmp_path, first)
    write_handshake(tmp_path, second)

    got = read_handshake(tmp_path)
    assert got == second
