"""Load bundled per-profession default profiles for the /hacienda:setup wizard.

Profile TOMLs live under ``piighost.compliance.profiles/<profession>.toml`` and
ship in the wheel. The loader is read-only and never touches user files.
"""
from __future__ import annotations

import logging
import re
import sys
from importlib import resources

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


_PROFESSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_LOGGER = logging.getLogger(__name__)


def load_bundled_profile(profession: str) -> dict:
    """Return the bundled default profile for *profession*, or ``{}`` if
    the profession is unknown or the input fails validation.

    The validation regex blocks path traversal — *profession* is reachable
    from the MCP boundary (untrusted).

    Returns ``{}`` for:
      - Invalid input (regex mismatch) — silent (this is normal flow).
      - Unknown profession (no bundled file) — silent (also normal).
      - TOMLDecodeError / OSError on a bundled file — logged as a WARNING,
        because that's a build-time bug we want CI to surface.
    """
    if not _PROFESSION_RE.match(profession or ""):
        return {}
    try:
        path = resources.files("piighost.compliance.profiles") / f"{profession}.toml"
        if not path.is_file():
            return {}
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Bundled file vanished mid-flight — silent fall-through.
        return {}
    except AttributeError:
        # AttributeError can fire when importlib.resources returns a
        # MultiplexedPath (namespace-package case) without an .is_file()
        # method — older Python layouts did this. Defence-in-depth on
        # current 3.13+ packaging where __init__.py guarantees .is_file().
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        _LOGGER.warning(
            "Failed to load bundled profile %r: %s. "
            "This is a build-time bug — the bundled TOML should always "
            "parse. Returning {} so the wizard can fall back to generic.",
            profession, exc,
        )
        return {}
