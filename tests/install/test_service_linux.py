# tests/install/test_service_linux.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux only")

from piighost.install.service import ServiceSpec
from piighost.install.service import linux as linux_mod


def _spec(tmp_path: Path) -> ServiceSpec:
    return ServiceSpec(
        name="piighost-proxy",
        bin_path="/usr/local/bin/piighost",
        vault_dir=tmp_path / ".piighost",
        cert_path=tmp_path / "leaf.pem",
        key_path=tmp_path / "leaf.key",
        port=443,
        user="alice",
    )


def test_unit_content_has_ambient_capabilities(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    content = linux_mod._unit_content(spec)
    assert "AmbientCapabilities=CAP_NET_BIND_SERVICE" in content


def test_unit_content_has_bin_and_port(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    content = linux_mod._unit_content(spec)
    assert "/usr/local/bin/piighost" in content
    assert "proxy run" in content
    assert "--port 443" in content


def test_install_writes_unit_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        linux_mod.install(spec)
    unit_dir = tmp_path / "config" / "systemd" / "user"
    assert (unit_dir / "piighost-proxy.service").exists()


def test_install_calls_systemctl_enable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        linux_mod.install(spec)
        argv_list = [" ".join(str(x) for x in c.args[0]) for c in mock_run.call_args_list]
        assert any("enable" in a for a in argv_list)


def test_uninstall_calls_disable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    unit_dir = tmp_path / "config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "piighost-proxy.service").write_text("", encoding="utf-8")
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        linux_mod.uninstall(spec)
        argv_list = [" ".join(str(x) for x in c.args[0]) for c in mock_run.call_args_list]
        assert any("disable" in a for a in argv_list)
    assert not (unit_dir / "piighost-proxy.service").exists()


def test_running_returns_true_on_exit_0(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert linux_mod.running(spec) is True


def test_running_returns_false_on_nonzero(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=3)
        assert linux_mod.running(spec) is False
