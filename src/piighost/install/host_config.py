"""Write ANTHROPIC_BASE_URL into Claude Code's settings.json."""
from __future__ import annotations

import json
from pathlib import Path

_KEY = "ANTHROPIC_BASE_URL"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_claude_code_base_url(settings: Path, url: str) -> None:
    data = _load(settings)
    env = data.setdefault("env", {})
    env[_KEY] = url
    _save(settings, data)


def remove_claude_code_base_url(settings: Path) -> None:
    if not settings.exists():
        return
    data = _load(settings)
    env = data.get("env", {})
    env.pop(_KEY, None)
    _save(settings, data)


def default_settings_path() -> Path:
    """~/.claude/settings.json on all platforms."""
    return Path.home() / ".claude" / "settings.json"
