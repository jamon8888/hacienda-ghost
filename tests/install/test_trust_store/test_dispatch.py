from __future__ import annotations

import sys
from pathlib import Path

import pytest

from piighost.install.trust_store import install_ca, uninstall_ca


def test_dispatch_calls_platform_installer(monkeypatch, tmp_path: Path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN CERT-----")
    called: dict = {}

    def fake(path: Path) -> None:
        called["path"] = path

    if sys.platform == "darwin":
        monkeypatch.setattr("piighost.install.trust_store.darwin.install", fake)
    elif sys.platform == "win32":
        monkeypatch.setattr("piighost.install.trust_store.windows.install", fake)
    else:
        monkeypatch.setattr("piighost.install.trust_store.linux.install", fake)

    install_ca(ca)
    assert called["path"] == ca
