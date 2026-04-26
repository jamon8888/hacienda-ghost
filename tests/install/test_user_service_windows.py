from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only", allow_module_level=True)

from unittest.mock import patch

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
        bin_path=Path(r"C:\tools\piighost.exe"),
        vault_dir=tmp_path / "vault",
        log_dir=tmp_path / "logs",
        listen_port=8443,
    )


def test_install_creates_scheduled_task(spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        install(spec)
    args_first = run.call_args_list[0].args[0]
    assert args_first[0].lower().endswith("schtasks.exe")
    assert "/create" in args_first
    assert "/sc" in args_first and "onlogon" in args_first
    assert "/rl" in args_first and "limited" in args_first
    assert any("piighost" in a.lower() for a in args_first)


def test_uninstall_deletes_task(spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        uninstall(spec)
    args_first = run.call_args_list[0].args[0]
    assert "/delete" in args_first
    assert "/f" in args_first


def test_status_reports_running(spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "Status: Running\r\n"
        result = status(spec)
    assert result == "running"


def test_status_reports_missing(spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 1
        run.return_value.stdout = ""
        result = status(spec)
    assert result == "missing"
