from __future__ import annotations
from contextlib import ExitStack
from unittest.mock import patch
from typer.testing import CliRunner
import pytest

from piighost.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_install_env(monkeypatch, tmp_path):
    """Keep install commands away from the real home dir and OS trust store.

    expanduser uses HOME on POSIX and USERPROFILE on Windows; both are
    redirected to tmp_path. PIIGHOST_SKIP_TRUSTSTORE/SERVICE prevent the
    light/strict modes from invoking certutil/security/launchctl on the
    host. trust_store.install_ca is also stubbed as a defense-in-depth
    no-op for legacy paths that don't honour the env vars.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PIIGHOST_SKIP_TRUSTSTORE", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_SERVICE", "1")
    import piighost.install.trust_store as ts
    monkeypatch.setattr(ts, "install_ca", lambda _p: None)


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
    # mode=light/strict short-circuit before preflight runs; pass a mode
    # outside that set so the legacy preflight branch is exercised.
    from piighost.install.preflight import PreflightError
    with patch("piighost.install.preflight.check_disk_space", side_effect=PreflightError("no space")):
        with patch("piighost.install.preflight.check_python_version"):
            result = runner.invoke(app, ["install", "--full", "--mode=legacy"])
    assert result.exit_code != 0
    assert "no space" in result.output
