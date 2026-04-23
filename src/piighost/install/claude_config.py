from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


class AlreadyRegisteredError(RuntimeError):
    pass


class MalformedConfigError(RuntimeError):
    pass


def find_claude_config() -> Path | None:
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        p = Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:
        p = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    return p if p.exists() else None


def backup_config(path: Path) -> Path:
    bak = path.with_suffix(".json.bak")
    shutil.copy2(path, bak)
    return bak


def merge_mcp_entry(
    path: Path, key: str, entry: dict, *, force: bool
) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MalformedConfigError(
            f"Cannot parse {path}: {exc}. Skipping config registration."
        ) from exc

    servers: dict = data.setdefault("mcpServers", {})
    if key in servers and not force:
        raise AlreadyRegisteredError(
            f"'{key}' already registered in {path}. Use --force to overwrite."
        )
    servers[key] = entry
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
