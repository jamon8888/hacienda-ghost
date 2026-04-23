from __future__ import annotations
from contextlib import ExitStack
from unittest.mock import patch
from typer.testing import CliRunner
import pytest

from piighost.cli.main import app

runner = CliRunner()


def _all_mocked():
    return [
        patch("piighost.install.preflight.check_disk_space"),
        patch("piighost.install.preflight.check_internet"),
        patch("piighost.install.preflight.check_python_version"),
        patch("piighost.install.docker.docker_available", return_value=False),
        patch("piighost.install.uv_path.ensure_uv", return_value="uv"),
        patch("piighost.install.uv_path.install_piighost"),
        patch("piighost.install.models.warmup_ner"),
        patch("piighost.install.models.warmup_embedder"),
        patch("piighost.install.claude_config.find_claude_config", return_value=None),
    ]


def test_install_dry_run_exits_zero():
    with ExitStack() as stack:
        for m in _all_mocked():
            stack.enter_context(m)
        result = runner.invoke(app, ["install", "--full", "--dry-run"])
    assert result.exit_code == 0


def test_install_no_docker_forces_uv_path():
    with ExitStack() as stack:
        for m in _all_mocked():
            stack.enter_context(m)
        result = runner.invoke(app, ["install", "--full", "--no-docker", "--dry-run"])
    assert result.exit_code == 0


def test_install_fails_gracefully_on_preflight_error():
    from piighost.install.preflight import PreflightError
    with patch("piighost.install.preflight.check_disk_space", side_effect=PreflightError("no space")):
        with patch("piighost.install.preflight.check_python_version"):
            result = runner.invoke(app, ["install", "--full"])
    assert result.exit_code != 0
    assert "no space" in result.output
