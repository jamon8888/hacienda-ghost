"""Load bundled per-profession default profiles for the /hacienda:setup wizard.

Profile TOMLs live under ``piighost.compliance.profiles/<profession>.toml`` and
ship in the wheel. The loader is read-only and never touches user files.
"""
from __future__ import annotations

import re
import sys
from importlib import resources

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


_PROFESSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def load_bundled_profile(profession: str) -> dict:
    """Return the bundled default profile for *profession*, or ``{}`` if
    the profession is unknown or the input fails validation.

    The validation regex blocks path traversal — *profession* is reachable
    from the MCP boundary (untrusted).
    """
    if not _PROFESSION_RE.match(profession or ""):
        return {}
    try:
        path = resources.files("piighost.compliance.profiles") / f"{profession}.toml"
        if not path.is_file():
            return {}
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, AttributeError, tomllib.TOMLDecodeError, OSError):
        # AttributeError can fire when importlib.resources returns a
        # MultiplexedPath (namespace-package case) without an .is_file()
        # method — older Python layouts did this. We keep the catch for
        # defence-in-depth even though our package layout uses __init__.py
        # and a regular package, where .is_file() is always defined.
        # Closes Phase 4 followup #8.
        return {}
