from __future__ import annotations

from pathlib import Path

from piighost.proxy.handshake import ProxyHandshake, read_handshake, write_handshake


def test_write_read_roundtrip(tmp_path: Path) -> None:
    hs = ProxyHandshake(pid=12345, port=8443, token="abc123")
    write_handshake(tmp_path, hs)
    got = read_handshake(tmp_path)
    assert got == hs


def test_read_missing_returns_none(tmp_path: Path) -> None:
    assert read_handshake(tmp_path) is None


def test_write_uses_atomic_rename(tmp_path: Path) -> None:
    hs = ProxyHandshake(pid=1, port=8443, token="t")
    write_handshake(tmp_path, hs)
    file = tmp_path / "proxy.handshake.json"
    assert file.exists()
    assert not (tmp_path / "proxy.handshake.json.tmp").exists()
