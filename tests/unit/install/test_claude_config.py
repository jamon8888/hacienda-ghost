from __future__ import annotations
import json
from pathlib import Path
import pytest

from piighost.install.claude_config import (
    backup_config,
    find_claude_config,
    merge_mcp_entry,
    AlreadyRegisteredError,
)

MCP_ENTRY = {
    "type": "stdio",
    "command": "uvx",
    "args": ["--from", "piighost[mcp,index,gliner2]", "piighost", "serve", "--transport", "stdio"],
    "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
}


def test_find_claude_config_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    result = find_claude_config()
    assert result is None


def test_backup_config_creates_bak(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text('{"mcpServers": {}}', encoding="utf-8")
    bak = backup_config(cfg)
    assert bak.exists()
    assert bak.suffix == ".bak"
    assert bak.read_text() == cfg.read_text()


def test_merge_mcp_entry_adds_new_key(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text('{"mcpServers": {}}', encoding="utf-8")
    merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=False)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piighost"] == MCP_ENTRY


def test_merge_mcp_entry_raises_if_already_registered(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"piighost": {"type": "stdio"}}}), encoding="utf-8"
    )
    with pytest.raises(AlreadyRegisteredError):
        merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=False)


def test_merge_mcp_entry_overwrites_with_force(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"piighost": {"type": "old"}}}), encoding="utf-8"
    )
    merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=True)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piighost"] == MCP_ENTRY


def test_merge_mcp_entry_preserves_other_servers(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"other": {"type": "stdio"}}}), encoding="utf-8"
    )
    merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=False)
    data = json.loads(cfg.read_text())
    assert "other" in data["mcpServers"]
    assert "piighost" in data["mcpServers"]


def test_merge_mcp_entry_handles_missing_mcp_servers_key(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text("{}", encoding="utf-8")
    merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=False)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piighost"] == MCP_ENTRY
