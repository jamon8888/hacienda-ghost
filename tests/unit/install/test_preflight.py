from __future__ import annotations
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from piighost.install.preflight import (
    PreflightError,
    check_disk_space,
    check_internet,
    check_python_version,
)


def test_check_disk_space_passes_when_enough(tmp_path):
    with patch("shutil.disk_usage") as mock_du:
        mock_du.return_value = MagicMock(free=9 * 1024**3)
        check_disk_space(min_gb=2.0)  # should not raise


def test_check_disk_space_raises_when_insufficient():
    with patch("shutil.disk_usage") as mock_du:
        mock_du.return_value = MagicMock(free=500 * 1024**2)  # 500 MB
        with pytest.raises(PreflightError, match="disk space"):
            check_disk_space(min_gb=2.0)


def test_check_internet_passes_when_reachable():
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        check_internet()  # should not raise


def test_check_internet_raises_when_unreachable():
    with patch("urllib.request.urlopen", side_effect=OSError("no network")):
        with pytest.raises(PreflightError, match="internet"):
            check_internet()


def test_check_python_version_passes():
    with patch("sys.version_info", (3, 12, 0)):
        check_python_version()  # should not raise


def test_check_python_version_raises_for_old_python():
    with patch("sys.version_info", (3, 9, 0)):
        with pytest.raises(PreflightError, match="Python 3.10"):
            check_python_version()
