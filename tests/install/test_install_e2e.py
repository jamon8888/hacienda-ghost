from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app


runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_install_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("PIIGHOST_SKIP_TRUSTSTORE", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_SERVICE", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_USERSVC", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_WARMUP", "1")
    import piighost.install.trust_store as ts
    monkeypatch.setattr(ts, "install_ca", lambda _p: None)
    return tmp_path


def test_install_full_with_yes_writes_settings(isolated_install_env):
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=full",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = json.loads(
        (isolated_install_env / ".claude" / "settings.json").read_text()
    )
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"
    assert "piighost" in settings["mcpServers"]


def test_install_mcp_only_no_base_url(isolated_install_env):
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=mcp-only",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = json.loads(
        (isolated_install_env / ".claude" / "settings.json").read_text()
    )
    assert "piighost" in settings["mcpServers"]
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_install_dry_run_does_nothing(isolated_install_env):
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=full",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--dry-run",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert not (isolated_install_env / ".claude" / "settings.json").exists()


def test_install_light_alias_emits_deprecation(isolated_install_env):
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=light",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert "[deprecated]" in result.output
    assert "--mode=light" in result.output


def test_install_strict_emits_advanced_warning(isolated_install_env):
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=strict",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--yes",
        ],
    )
    assert "[advanced]" in result.output
