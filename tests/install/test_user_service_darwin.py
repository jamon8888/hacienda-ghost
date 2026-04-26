from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

if sys.platform != "darwin":
    pytest.skip("macos-only", allow_module_level=True)

from unittest.mock import patch

from piighost.install.service.user_service import (
    UserServiceSpec,
    install,
    uninstall,
    status,
)


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def spec(tmp_path):
    return UserServiceSpec(
        name="com.piighost.proxy",
        bin_path=Path("/usr/local/bin/piighost"),
        vault_dir=tmp_path / "vault",
        log_dir=tmp_path / "logs",
        listen_port=8443,
    )


def test_install_writes_plist(isolated_home, spec):
    with patch("subprocess.run") as run:
        install(spec)
    plist_path = isolated_home / "Library" / "LaunchAgents" / "com.piighost.proxy.plist"
    assert plist_path.exists()
    data = plistlib.loads(plist_path.read_bytes())
    assert data["Label"] == "com.piighost.proxy"
    assert data["KeepAlive"] is True
    assert data["ThrottleInterval"] == 10
    assert "/usr/local/bin/piighost" in data["ProgramArguments"]
    run.assert_any_call(["launchctl", "load", "-w", str(plist_path)], check=True)


def test_uninstall_unloads_and_removes(isolated_home, spec):
    plist_path = isolated_home / "Library" / "LaunchAgents" / "com.piighost.proxy.plist"
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(b"<plist></plist>")
    with patch("subprocess.run") as run:
        uninstall(spec)
    assert not plist_path.exists()
    run.assert_any_call(["launchctl", "unload", "-w", str(plist_path)], check=False)


def test_status_reports_running(isolated_home, spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "1234\t0\tcom.piighost.proxy\n"
        result = status(spec)
    assert result == "running"
