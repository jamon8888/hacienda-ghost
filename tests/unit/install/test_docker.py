from __future__ import annotations
import subprocess
from unittest.mock import patch, MagicMock
import pytest

from piighost.install.docker import docker_available, compose_pull_and_up, DockerError


def test_docker_available_returns_true_when_daemon_running():
    with patch("piighost.install.docker.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert docker_available() is True


def test_docker_available_returns_false_when_not_found():
    with patch("piighost.install.docker.subprocess.run", side_effect=FileNotFoundError()):
        assert docker_available() is False


def test_docker_available_returns_false_when_daemon_not_running():
    with patch("piighost.install.docker.subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")):
        assert docker_available() is False


def test_compose_pull_and_up_dry_run_skips_subprocess():
    with patch("piighost.install.docker.subprocess.run") as mock_run:
        compose_pull_and_up(dry_run=True)
        mock_run.assert_not_called()


def test_compose_pull_and_up_calls_pull_then_up():
    calls = []
    def capture(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)
    with patch("piighost.install.docker.subprocess.run", side_effect=capture):
        with patch("piighost.install.docker._wait_for_healthy", return_value=True):
            compose_pull_and_up(dry_run=False)
    assert any("pull" in c for c in calls)
    assert any("up" in c for c in calls)


def test_compose_pull_and_up_raises_on_pull_failure():
    with patch("piighost.install.docker.subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")):
        with pytest.raises(DockerError, match="compose pull failed"):
            compose_pull_and_up(dry_run=False)
