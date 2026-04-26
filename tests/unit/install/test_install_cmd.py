from __future__ import annotations

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
    monkeypatch.setenv("PIIGHOST_SKIP_USERSVC", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_WARMUP", "1")
    import piighost.install.trust_store as ts
    monkeypatch.setattr(ts, "install_ca", lambda _p: None)


def test_install_dry_run_exits_zero():
    result = runner.invoke(
        app, ["install", "--mode=full", "--clients=code", "--dry-run", "--yes"]
    )
    assert result.exit_code == 0


def test_install_no_user_service_in_mcp_only():
    result = runner.invoke(
        app, ["install", "--mode=mcp-only", "--clients=code",
              "--no-user-service", "--yes"]
    )
    assert result.exit_code == 0


def test_install_fails_gracefully_on_invalid_mode():
    result = runner.invoke(
        app, ["install", "--mode=galaxybrain", "--yes"]
    )
    assert result.exit_code != 0
    assert "unknown mode" in result.output


def test_install_light_emits_deprecation():
    result = runner.invoke(
        app, ["install", "--mode=light", "--clients=code", "--yes"]
    )
    assert "[deprecated]" in result.output
