from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.platform != "linux":
    pytest.skip("linux-only", allow_module_level=True)

from unittest.mock import call, patch

from piighost.install.service.user_service import (
    UserServiceSpec,
    install,
    uninstall,
    status,
)


@pytest.fixture
def spec(tmp_path):
    return UserServiceSpec(
        name="com.piighost.proxy",
        bin_path=Path("/usr/local/bin/piighost"),
        vault_dir=tmp_path / "vault",
        log_dir=tmp_path / "logs",
        listen_port=8443,
    )


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    return tmp_path


def test_install_writes_service_unit(isolated_home, spec):
    with patch("subprocess.run") as run:
        install(spec)
    unit_path = isolated_home / ".config" / "systemd" / "user" / "piighost-proxy.service"
    assert unit_path.exists()
    content = unit_path.read_text()
    assert "ExecStart=/usr/local/bin/piighost serve" in content
    assert "Restart=on-failure" in content
    assert f"PIIGHOST_VAULT_DIR={spec.vault_dir}" in content
    run.assert_any_call(
        ["systemctl", "--user", "daemon-reload"], check=True
    )
    run.assert_any_call(
        ["systemctl", "--user", "enable", "--now", "piighost-proxy.service"], check=True
    )
    run.assert_any_call(
        ["loginctl", "enable-linger", isolated_home.name], check=False
    )


def test_uninstall_disables_and_removes(isolated_home, spec):
    unit_path = isolated_home / ".config" / "systemd" / "user" / "piighost-proxy.service"
    unit_path.parent.mkdir(parents=True)
    unit_path.write_text("placeholder")
    with patch("subprocess.run") as run:
        uninstall(spec)
    assert not unit_path.exists()
    run.assert_any_call(
        ["systemctl", "--user", "disable", "--now", "piighost-proxy.service"], check=False
    )


def test_status_reports_running(isolated_home, spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "active\n"
        result = status(spec)
    assert result == "running"


def test_status_reports_stopped(isolated_home, spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 3
        run.return_value.stdout = "inactive\n"
        result = status(spec)
    assert result == "stopped"
