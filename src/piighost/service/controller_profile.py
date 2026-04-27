"""Loader + merger for ``~/.piighost/controller.toml`` + per-project overrides.

Resolution order (highest priority first when merging):
  1. ``~/.piighost/projects/<project>/controller_overrides.toml``
  2. ``~/.piighost/controller.toml``

Atomic writes via tempfile + os.replace so a concurrent reader sees
either the old contents or the new ones, never half-written TOML.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def _to_toml_str(data: dict[str, Any]) -> str:
    """Minimal TOML serializer for the shapes we use (controller, dpo,
    defaults, mentions_legales). Stdlib has no TOML writer until 3.13;
    we keep deps tight by hand-rolling for our subset."""
    lines: list[str] = []
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(_format_scalar_line(k, v))
    for k, v in data.items():
        if isinstance(v, dict):
            lines.append("")
            lines.append(f"[{k}]")
            for kk, vv in v.items():
                lines.append(_format_scalar_line(kk, vv))
    return "\n".join(lines).strip() + "\n"


def _format_scalar_line(k: str, v: Any) -> str:
    if isinstance(v, bool):
        return f"{k} = {'true' if v else 'false'}"
    if isinstance(v, (int, float)):
        return f"{k} = {v}"
    if isinstance(v, str):
        esc = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'{k} = "{esc}"'
    if isinstance(v, list):
        items = []
        for item in v:
            if isinstance(item, str):
                esc = item.replace("\\", "\\\\").replace('"', '\\"')
                items.append(f'"{esc}"')
            else:
                items.append(str(item))
        return f"{k} = [" + ", ".join(items) + "]"
    if v is None:
        return f'{k} = ""'
    raise TypeError(f"Unsupported TOML value type for {k!r}: {type(v).__name__}")


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge ``override`` into ``base``. Returns a new dict."""
    out = {**base}
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class ControllerProfileService:
    """Read + write the controller profile (global + per-project override)."""

    def __init__(self, vault_dir: Path) -> None:
        self._global_path = Path.home() / ".piighost" / "controller.toml"
        self._vault_dir = vault_dir

    def _project_override_path(self, project: str) -> Path:
        return Path.home() / ".piighost" / "projects" / project / "controller_overrides.toml"

    def has_global(self) -> bool:
        return self._global_path.exists()

    def get(self, *, scope: Literal["global", "project"], project: str | None = None) -> dict:
        global_cfg = self._load_global()
        if scope == "global":
            return global_cfg
        if scope == "project":
            if not project:
                raise ValueError("project name is required when scope='project'")
            override_path = self._project_override_path(project)
            if override_path.exists():
                try:
                    override = tomllib.loads(override_path.read_text("utf-8"))
                except (tomllib.TOMLDecodeError, OSError):
                    override = {}
                return _deep_merge(global_cfg, override)
            return global_cfg
        raise ValueError(f"unknown scope: {scope!r}")

    def set(self, profile: dict, *, scope: Literal["global", "project"], project: str | None = None) -> None:
        if scope == "global":
            target = self._global_path
        elif scope == "project":
            if not project:
                raise ValueError("project name is required when scope='project'")
            target = self._project_override_path(project)
        else:
            raise ValueError(f"unknown scope: {scope!r}")
        _atomic_write(target, _to_toml_str(profile))

    def _load_global(self) -> dict:
        if not self._global_path.exists():
            return {}
        try:
            return tomllib.loads(self._global_path.read_text("utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return {}
