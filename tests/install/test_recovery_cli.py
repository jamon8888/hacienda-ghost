from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app
from piighost.install.clients import register
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


runner = CliRunner()


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def _seed_full_install(home: Path) -> None:
    plan = InstallPlan(
        mode=Mode.FULL,
        vault_dir=home / "vault",
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=frozenset({Client.CLAUDE_CODE}),
        install_user_service=True,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    register(plan, Client.CLAUDE_CODE)


def test_disconnect_command_removes_base_url(isolated_home):
    _seed_full_install(isolated_home)
    result = runner.invoke(app, ["disconnect"])
    assert result.exit_code == 0
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_connect_command_re_adds_base_url(isolated_home):
    _seed_full_install(isolated_home)
    runner.invoke(app, ["disconnect"])
    result = runner.invoke(app, ["connect"])
    assert result.exit_code == 0
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"
