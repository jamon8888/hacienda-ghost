from __future__ import annotations

import json
from pathlib import Path

import pytest

from piighost.install.clients import register
from piighost.install.plan import Client, Embedder, InstallPlan, Mode
from piighost.install.recovery import connect, disconnect


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def _full_plan(home: Path) -> InstallPlan:
    return InstallPlan(
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


def test_disconnect_removes_base_url_keeps_mcp(isolated_home):
    register(_full_plan(isolated_home), Client.CLAUDE_CODE)
    disconnect(frozenset({Client.CLAUDE_CODE}))
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})
    assert "piighost" in settings["mcpServers"]


def test_connect_re_adds_base_url(isolated_home):
    register(_full_plan(isolated_home), Client.CLAUDE_CODE)
    disconnect(frozenset({Client.CLAUDE_CODE}))
    connect(frozenset({Client.CLAUDE_CODE}))
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"


def test_disconnect_default_targets_all_existing_clients(isolated_home):
    register(_full_plan(isolated_home), Client.CLAUDE_CODE)
    disconnect(None)  # default = all detected
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_connect_no_op_when_no_config_exists(isolated_home):
    # Should not raise even though no settings file exists
    connect(frozenset({Client.CLAUDE_CODE}))
