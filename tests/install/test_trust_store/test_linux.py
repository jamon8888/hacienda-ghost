from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux only")


def test_install_debian_style(monkeypatch, tmp_path: Path) -> None:
    from piighost.install.trust_store import linux

    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> None:
        calls.append(cmd)
        # Simulate the cp command by actually copying the file
        if "cp" in cmd:
            import shutil as _shutil
            _shutil.copy(cmd[-2], cmd[-1])

    monkeypatch.setattr(linux, "_run", fake_run)
    monkeypatch.setattr(linux, "_detect_family", lambda: "debian")
    monkeypatch.setattr(linux, "_DEBIAN_DIR", tmp_path)

    ca = tmp_path / "src.pem"
    ca.write_bytes(b"-----BEGIN-----")

    linux.install(ca)

    target = tmp_path / "piighost.crt"
    assert target.exists()
    assert any("update-ca-certificates" in " ".join(c) for c in calls)


def test_install_fedora_style(monkeypatch, tmp_path: Path) -> None:
    from piighost.install.trust_store import linux

    calls: list[list[str]] = []
    monkeypatch.setattr(linux, "_run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(linux, "_detect_family", lambda: "fedora")

    ca = tmp_path / "src.pem"
    ca.write_bytes(b"-----BEGIN-----")

    linux.install(ca)

    assert any("trust" in c and "anchor" in c for c in calls)
