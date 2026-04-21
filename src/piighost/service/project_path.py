"""Auto-derive a project name from a filesystem path."""

from __future__ import annotations

import re
from pathlib import Path


_GENERIC_NAMES = frozenset(
    {
        "documents",
        "desktop",
        "downloads",
        "src",
        "tmp",
        "var",
        "home",
        "users",
        "projects",
        "data",
        "docs",
    }
)

_VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def derive_project_from_path(path: Path) -> str:
    """Return the first path component that looks like a project name.

    Walks from the path's parent toward the root, skipping generic names
    (``documents``, ``src``, ``projects``, ...) and names with invalid
    characters. Returns ``"default"`` if no suitable candidate is found.

    Uses ``absolute()`` rather than ``resolve()`` so symlinks are not
    followed — otherwise on macOS ``/tmp`` resolves to ``/private/tmp``
    and the derivation would pick up ``"private"`` as a project name.
    """
    resolved = path.absolute()
    parts = [p for p in resolved.parts if p not in ("/", "\\")]
    parts = [p for p in parts if not (len(p) == 2 and p.endswith(":"))]
    for candidate in reversed(parts[:-1]):
        if candidate.lower() in _GENERIC_NAMES:
            continue
        if not _VALID_NAME_RE.fullmatch(candidate):
            continue
        return candidate
    return "default"
