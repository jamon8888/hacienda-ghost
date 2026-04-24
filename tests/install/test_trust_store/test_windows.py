from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_install_calls_certutil_addstore(monkeypatch, tmp_path: Path) -> None:
    from piighost.install.trust_store import windows

    calls: list[list[str]] = []
    monkeypatch.setattr(windows, "_run", lambda cmd: calls.append(cmd))

    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN-----")
    windows.install(ca)

    assert any("-addstore" in c for c in calls)
    assert any("Root" in c for c in calls)


def test_uninstall_calls_certutil_delstore(monkeypatch, tmp_path: Path) -> None:
    from piighost.install.trust_store import windows

    calls: list[list[str]] = []
    monkeypatch.setattr(windows, "_run", lambda cmd: calls.append(cmd))
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN-----")

    windows.uninstall(ca)
    assert any("-delstore" in c for c in calls)
