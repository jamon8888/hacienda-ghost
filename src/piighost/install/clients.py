"""Detect installed Claude clients and register/unregister the
piighost MCP server + ANTHROPIC_BASE_URL env var.

Two clients are supported:
- Claude Code → ~/.claude/settings.json
- Claude Desktop → platform-specific claude_desktop_config.json
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from piighost.install.plan import Client, InstallPlan, Mode


_PROXY_BASE_URL = "https://localhost:8443"
_BACKUP_SUFFIX = ".piighost.bak"


@dataclass(frozen=True)
class ClientLocation:
    client: Client
    config_path: Path
    exists: bool


def claude_code_settings_path() -> Path:
    home = Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or Path.home())
    return home / ".claude" / "settings.json"


def claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return (
            Path(os.environ.get("HOME") or Path.home())
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata is None:
            appdata = str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    return (
        Path(os.environ.get("HOME") or Path.home())
        / ".config"
        / "Claude"
        / "claude_desktop_config.json"
    )


def detect_all() -> list[ClientLocation]:
    code = claude_code_settings_path()
    desktop = claude_desktop_config_path()
    return [
        ClientLocation(client=Client.CLAUDE_CODE, config_path=code, exists=code.exists()),
        ClientLocation(client=Client.CLAUDE_DESKTOP, config_path=desktop, exists=desktop.exists()),
    ]


def _mcp_entry(plan: InstallPlan) -> dict:
    return {
        "command": "uvx",
        "args": [
            "--from",
            "piighost[mcp,index,gliner2,cache]",
            "piighost",
            "serve",
            "--transport",
            "stdio",
        ],
        "env": {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PIIGHOST_VAULT_DIR": str(plan.vault_dir),
        },
    }


def register(plan: InstallPlan, client: Client) -> None:
    """Write the MCP entry (and BASE_URL env, for Claude Code) into the
    client's config file. Idempotent: re-registering with the same plan
    is a no-op."""
    location = _location_for(client)
    config = _read_config(location.config_path)

    desired_entry = _mcp_entry(plan)
    existing = config.get("mcpServers", {}).get("piighost")
    if existing is not None and existing != desired_entry and not plan.force:
        raise RuntimeError(
            f"conflict: mcpServers.piighost in {location.config_path} differs "
            f"from desired entry. Re-run with --force to overwrite."
        )

    if location.config_path.exists() and not _backup_path(location.config_path).exists():
        _write_backup(location.config_path)

    config.setdefault("mcpServers", {})["piighost"] = desired_entry
    if plan.mode is Mode.FULL and client is Client.CLAUDE_CODE:
        config.setdefault("env", {})["ANTHROPIC_BASE_URL"] = _PROXY_BASE_URL
    _write_config(location.config_path, config)


def unregister(
    client: Client, *, remove_base_url: bool, remove_mcp: bool
) -> None:
    """Remove the requested pieces from the client's config. No-op if
    the config file is missing."""
    location = _location_for(client)
    if not location.config_path.exists():
        return
    config = _read_config(location.config_path)
    if remove_mcp:
        config.get("mcpServers", {}).pop("piighost", None)
    if remove_base_url:
        config.get("env", {}).pop("ANTHROPIC_BASE_URL", None)
    _write_config(location.config_path, config)


def _location_for(client: Client) -> ClientLocation:
    for loc in detect_all():
        if loc.client is client:
            return loc
    raise KeyError(client)


def read_config(path: Path) -> dict:
    """Public: load a Claude client config (or return {} if missing)."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_config(path: Path, data: dict) -> None:
    """Public: write a Claude client config. Raises RuntimeError with a
    remediation hint if the path is read-only or the directory cannot
    be created (e.g. enterprise-managed installs)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except PermissionError as exc:
        raise RuntimeError(
            f"cannot write {path}: {exc}. The file or its parent "
            f"directory is read-only. If your Claude install is "
            f"enterprise-managed, edit the config manually with the "
            f"piighost MCP entry shown by `piighost install --dry-run`."
        ) from exc


# Internal aliases preserved for callers that imported the underscored
# names before they were promoted to public.
_read_config = read_config
_write_config = write_config


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + _BACKUP_SUFFIX)


def _write_backup(path: Path) -> None:
    bak = _backup_path(path)
    if bak.exists():
        return
    bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
