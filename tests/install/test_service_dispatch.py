# tests/install/test_service_dispatch.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from piighost.install.service import ServiceSpec, install_service, service_running, uninstall_service


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


def test_service_spec_fields(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    assert spec.port == 443
    assert spec.user == "alice"
    assert spec.name == "com.piighost.proxy"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_dispatch_darwin(tmp_path: Path) -> None:
    mock = MagicMock()
    with patch("piighost.install.service.darwin", mock):
        install_service(_spec(tmp_path))
        mock.install.assert_called_once()


@pytest.mark.skipif(sys.platform in ("darwin", "win32"), reason="Linux only")
def test_dispatch_linux(tmp_path: Path) -> None:
    mock = MagicMock()
    with patch("piighost.install.service.linux", mock):
        install_service(_spec(tmp_path))
        mock.install.assert_called_once()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_dispatch_windows(tmp_path: Path) -> None:
    mock = MagicMock()
    with patch("piighost.install.service.windows", mock):
        install_service(_spec(tmp_path))
        mock.install.assert_called_once()
