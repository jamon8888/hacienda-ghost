# tests/install/test_service_darwin.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")

from piighost.install.service import ServiceSpec
from piighost.install.service import darwin as darwin_mod


def _spec(tmp_path: Path) -> ServiceSpec:
    return ServiceSpec(
        name="com.piighost.proxy",
        bin_path="/usr/local/bin/piighost",
        vault_dir=tmp_path / ".piighost",
        cert_path=tmp_path / "leaf.pem",
        key_path=tmp_path / "leaf.key",
        port=443,
        user="alice",
    )


def test_plist_content_contains_label(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    content = darwin_mod._plist_content(spec)
    assert "com.piighost.proxy" in content
    assert "/usr/local/bin/piighost" in content
    assert "443" in content
    assert str(tmp_path / ".piighost") in content
    assert str(tmp_path / "leaf.pem") in content


def test_plist_content_is_valid_xml(tmp_path: Path) -> None:
    from xml.etree import ElementTree as ET
    spec = _spec(tmp_path)
    content = darwin_mod._plist_content(spec)
    ET.fromstring(content)  # must not raise


def test_plist_keepalive_with_throttle(tmp_path: Path) -> None:
    """KeepAlive=true brings the daemon back; ThrottleInterval prevents
    a crash loop from hammering launchd faster than once per N seconds.
    """
    spec = _spec(tmp_path)
    content = darwin_mod._plist_content(spec)
    assert "<key>KeepAlive</key>" in content
    assert "<key>ThrottleInterval</key>" in content
    # ExitTimeOut limits how long launchd waits for graceful shutdown
    # before sending SIGKILL — keeps restart latency bounded.
    assert "<key>ExitTimeOut</key>" in content


def test_install_calls_sudo(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.darwin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        darwin_mod.install(spec)
        argv_list = [c.args[0] for c in mock_run.call_args_list]
        assert any("launchctl" in str(a) for a in argv_list)
        assert any("sudo" in str(a) for a in argv_list)


def test_uninstall_calls_unload(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.darwin.subprocess.run") as mock_run, \
         patch("piighost.install.service.darwin._PLIST_PATH") as mock_path:
        mock_path.exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        darwin_mod.uninstall(spec)
        argv_list = [c.args[0] for c in mock_run.call_args_list]
        assert any("unload" in str(a) for a in argv_list)


def test_running_returns_true_when_launchctl_exits_0(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.darwin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert darwin_mod.running(spec) is True


def test_running_returns_false_when_launchctl_exits_nonzero(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.darwin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert darwin_mod.running(spec) is False
