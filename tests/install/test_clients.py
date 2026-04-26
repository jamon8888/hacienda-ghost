from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from piighost.install.clients import (
    ClientLocation,
    detect_all,
    register,
    unregister,
)
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _plan(tmp_path: Path, **overrides) -> InstallPlan:
    base = dict(
        mode=Mode.FULL,
        vault_dir=tmp_path / "vault",
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=frozenset({Client.CLAUDE_CODE}),
        install_user_service=True,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    base.update(overrides)
    return InstallPlan(**base)


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def test_detect_all_returns_both_clients(isolated_home):
    locs = {loc.client: loc for loc in detect_all()}
    assert Client.CLAUDE_CODE in locs
    assert Client.CLAUDE_DESKTOP in locs
    for loc in locs.values():
        assert isinstance(loc, ClientLocation)
        assert loc.exists is False  # nothing pre-existing


def test_detect_all_marks_existing_config(isolated_home):
    code_settings = isolated_home / ".claude" / "settings.json"
    code_settings.parent.mkdir(parents=True)
    code_settings.write_text("{}")
    found = {loc.client: loc.exists for loc in detect_all()}
    assert found[Client.CLAUDE_CODE] is True
    assert found[Client.CLAUDE_DESKTOP] is False


def test_register_writes_mcp_entry_and_base_url_for_claude_code(isolated_home):
    plan = _plan(isolated_home, mode=Mode.FULL)
    register(plan, Client.CLAUDE_CODE)
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "mcpServers" in settings
    assert "piighost" in settings["mcpServers"]
    assert settings["mcpServers"]["piighost"]["command"] == "uvx"
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"


def test_register_in_mcp_only_mode_skips_base_url(isolated_home):
    plan = _plan(
        isolated_home, mode=Mode.MCP_ONLY, install_user_service=False
    )
    register(plan, Client.CLAUDE_CODE)
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "piighost" in settings["mcpServers"]
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_register_creates_backup_on_first_write(isolated_home):
    code_settings = isolated_home / ".claude" / "settings.json"
    code_settings.parent.mkdir(parents=True)
    code_settings.write_text(json.dumps({"keep_me": "yes"}))
    plan = _plan(isolated_home)
    register(plan, Client.CLAUDE_CODE)
    bak = code_settings.with_suffix(".json.piighost.bak")
    assert bak.exists()
    assert json.loads(bak.read_text()) == {"keep_me": "yes"}


def test_register_is_idempotent(isolated_home):
    plan = _plan(isolated_home)
    register(plan, Client.CLAUDE_CODE)
    register(plan, Client.CLAUDE_CODE)  # same plan, second time
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert settings["mcpServers"]["piighost"]["command"] == "uvx"


def test_register_conflict_without_force_raises(isolated_home):
    code_settings = isolated_home / ".claude" / "settings.json"
    code_settings.parent.mkdir(parents=True)
    code_settings.write_text(json.dumps({
        "mcpServers": {
            "piighost": {"command": "different", "args": []}
        }
    }))
    plan = _plan(isolated_home)
    with pytest.raises(RuntimeError, match="conflict"):
        register(plan, Client.CLAUDE_CODE)


def test_register_conflict_with_force_overwrites(isolated_home):
    code_settings = isolated_home / ".claude" / "settings.json"
    code_settings.parent.mkdir(parents=True)
    code_settings.write_text(json.dumps({
        "mcpServers": {
            "piighost": {"command": "different", "args": []}
        }
    }))
    plan = _plan(isolated_home, force=True)
    register(plan, Client.CLAUDE_CODE)
    settings = json.loads(code_settings.read_text())
    assert settings["mcpServers"]["piighost"]["command"] == "uvx"


def test_unregister_removes_only_requested_pieces(isolated_home):
    plan = _plan(isolated_home)
    register(plan, Client.CLAUDE_CODE)
    unregister(Client.CLAUDE_CODE, remove_base_url=True, remove_mcp=False)
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "piighost" in settings["mcpServers"]
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_unregister_no_op_when_config_missing(isolated_home):
    # Should not raise
    unregister(Client.CLAUDE_CODE, remove_base_url=True, remove_mcp=True)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS path")
def test_detect_claude_desktop_macos(isolated_home):
    desktop = (
        isolated_home
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json"
    )
    desktop.parent.mkdir(parents=True)
    desktop.write_text("{}")
    found = {loc.client: loc.exists for loc in detect_all()}
    assert found[Client.CLAUDE_DESKTOP] is True
