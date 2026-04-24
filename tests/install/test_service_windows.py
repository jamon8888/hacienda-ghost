# tests/install/test_service_windows.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

from piighost.install.service import ServiceSpec
from piighost.install.service import windows as windows_mod


def _spec(tmp_path: Path) -> ServiceSpec:
    return ServiceSpec(
        name="piighost-proxy",
        bin_path=r"C:\tools\piighost.exe",
        vault_dir=tmp_path / ".piighost",
        cert_path=tmp_path / "leaf.pem",
        key_path=tmp_path / "leaf.key",
        port=443,
        user="alice",
    )


def test_urlacl_url(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    assert windows_mod._urlacl_url(spec) == "https://127.0.0.1:443/"


def test_install_calls_netsh_and_schtasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("USERNAME", "alice")
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        windows_mod.install(spec)
        argv_list = [" ".join(str(x) for x in c.args[0]) for c in mock_run.call_args_list]
        assert any("netsh" in a for a in argv_list)
        assert any("schtasks" in a and "/create" in a for a in argv_list)


def test_install_schtasks_uses_onlogon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("USERNAME", "alice")
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        windows_mod.install(spec)
        schtasks_call = next(
            c for c in mock_run.call_args_list if "schtasks" in str(c.args[0])
        )
        args_flat = " ".join(str(x) for x in schtasks_call.args[0])
        assert "ONLOGON" in args_flat
        assert "HIGHEST" in args_flat


def test_uninstall_deletes_task_and_urlacl(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        windows_mod.uninstall(spec)
        argv_list = [" ".join(str(x) for x in c.args[0]) for c in mock_run.call_args_list]
        assert any("schtasks" in a and "/delete" in a for a in argv_list)
        assert any("netsh" in a and "delete" in a for a in argv_list)


def test_running_true_when_query_shows_running(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"Status: Running")
        assert windows_mod.running(spec) is True


def test_running_false_when_task_missing(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout=b"")
        assert windows_mod.running(spec) is False
