from __future__ import annotations
import subprocess
from unittest.mock import patch, MagicMock
import pytest

from piighost.install.uv_path import ensure_uv, install_piighost, UvNotFoundError


def test_ensure_uv_returns_path_when_found():
    with patch("piighost.install.uv_path.shutil.which", return_value="/usr/local/bin/uv"):
        path = ensure_uv()
        assert path == "/usr/local/bin/uv"


def test_ensure_uv_raises_when_missing():
    with patch("piighost.install.uv_path.shutil.which", return_value=None):
        with pytest.raises(UvNotFoundError):
            ensure_uv()


def test_install_piighost_dry_run_returns_without_subprocess():
    with patch("subprocess.run") as mock_run:
        install_piighost(uv_path="uv", dry_run=True)
        mock_run.assert_not_called()


def test_install_piighost_calls_uv_tool_install():
    with patch("piighost.install.uv_path.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        install_piighost(uv_path="uv", dry_run=False)
        args = mock_run.call_args[0][0]
        assert "uv" in args
        assert "tool" in args
        assert "install" in args
        assert any("piighost" in a for a in args)


def test_install_piighost_raises_on_subprocess_failure():
    with patch("piighost.install.uv_path.subprocess.run", side_effect=subprocess.CalledProcessError(1, "uv")):
        with pytest.raises(RuntimeError, match="uv tool install failed"):
            install_piighost(uv_path="uv", dry_run=False)
