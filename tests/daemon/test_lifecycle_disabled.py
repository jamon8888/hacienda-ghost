"""The daemon.disabled flag is honored by ensure_daemon and stop_daemon."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from piighost.daemon.exceptions import DaemonDisabled
from piighost.daemon.lifecycle import ensure_daemon, start_daemon, stop_daemon


def test_ensure_daemon_raises_when_disabled_flag_present(tmp_path: Path) -> None:
    (tmp_path / "daemon.disabled").touch()
    with pytest.raises(DaemonDisabled):
        ensure_daemon(tmp_path)


def test_stop_daemon_writes_disabled_flag(tmp_path: Path) -> None:
    # No daemon to stop, but the flag must still be written so future
    # ensure_daemon calls are blocked.
    stop_daemon(tmp_path)
    assert (tmp_path / "daemon.disabled").exists()


def test_start_daemon_removes_disabled_flag(tmp_path: Path) -> None:
    (tmp_path / "daemon.disabled").touch()
    # Patch the actual spawn so the test doesn't fork a real daemon.
    with patch("piighost.daemon.lifecycle.ensure_daemon") as mock_ensure:
        mock_ensure.return_value = None
        start_daemon(tmp_path)
    assert not (tmp_path / "daemon.disabled").exists()
    # Verify ensure_daemon was invoked, but don't assert exact args — that
    # over-couples the test to the start_daemon → ensure_daemon plumbing.
    # The behavioral contract is "flag removed AND daemon-up attempted".
    assert mock_ensure.called


def test_disabled_flag_persists_when_daemon_was_already_stopped(tmp_path: Path) -> None:
    """stop_daemon is idempotent and always leaves the flag in place."""
    stop_daemon(tmp_path)
    stop_daemon(tmp_path)  # second call must not crash
    assert (tmp_path / "daemon.disabled").exists()
