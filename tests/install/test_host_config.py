from __future__ import annotations

import json
from pathlib import Path

from piighost.install.host_config import (
    remove_claude_code_base_url,
    set_claude_code_base_url,
)


def test_sets_base_url_in_fresh_settings(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    set_claude_code_base_url(settings, "https://localhost:8443")
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"


def test_preserves_existing_keys(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"theme": "dark", "env": {"OTHER": "x"}}),
        encoding="utf-8",
    )
    set_claude_code_base_url(settings, "https://localhost:8443")
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert data["env"]["OTHER"] == "x"
    assert data["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"


def test_remove_base_url_leaves_other_env_untouched(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {"env": {"ANTHROPIC_BASE_URL": "https://localhost:8443", "OTHER": "x"}}
        ),
        encoding="utf-8",
    )
    remove_claude_code_base_url(settings)
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "ANTHROPIC_BASE_URL" not in data["env"]
    assert data["env"]["OTHER"] == "x"
