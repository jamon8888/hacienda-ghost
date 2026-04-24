from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def test_install_invokes_security_add_trusted_cert(monkeypatch, tmp_path: Path) -> None:
    from piighost.install.trust_store import darwin

    calls: list[list[str]] = []
    monkeypatch.setattr(darwin, "_run", lambda cmd: calls.append(cmd))
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN-----")

    darwin.install(ca)

    assert calls, "no subprocess call made"
    cmd = calls[0]
    assert cmd[0] == "sudo"
    assert "add-trusted-cert" in cmd
    assert str(ca) in cmd


def test_uninstall_invokes_security_remove_trusted_cert(monkeypatch, tmp_path: Path) -> None:
    from piighost.install.trust_store import darwin

    calls: list[list[str]] = []
    monkeypatch.setattr(darwin, "_run", lambda cmd: calls.append(cmd))
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN-----")

    darwin.uninstall(ca)

    assert calls
    assert "remove-trusted-cert" in calls[0]
