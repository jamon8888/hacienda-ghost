"""Map raw indexer ``error_message`` strings to a bounded category enum.

The ``indexed_files`` table stores ``error_message`` as
``f"{type(exc).__name__}: {exc}"``. Raw exception text can contain file
paths or document fragments that are PII, so the service boundary
exposes only the bounded category returned by :func:`classify`.

Category vocabulary (additive-only, never rename):

- ``password_protected`` — file requires a credential to open
- ``corrupt``            — file structure is invalid / unreadable
- ``unsupported_format`` — extension or signature has no extractor
- ``timeout``            — extraction exceeded its time budget
- ``other``              — anything else, including ``None`` / empty input
"""
from __future__ import annotations

# Order matters: first match wins. Keep most specific patterns first.
_TAXONOMY: tuple[tuple[str, str], ...] = (
    ("password",          "password_protected"),
    ("encrypted",         "password_protected"),
    ("could not decrypt", "password_protected"),
    ("corrupt",           "corrupt"),
    ("invalid pdf",       "corrupt"),
    ("malformed",         "corrupt"),
    ("unsupported",       "unsupported_format"),
    ("no extractor",      "unsupported_format"),
    ("not supported",     "unsupported_format"),
    ("timeout",           "timeout"),
    ("timed out",         "timeout"),
)


def classify(error_message: str | None) -> str:
    """Return the bounded category for ``error_message``.

    Matches case-insensitively against substrings in ``_TAXONOMY`` in
    declaration order; first match wins. Returns ``"other"`` for
    unrecognised messages, the empty string, and ``None``.

    Never returns the input string directly — this is a hard invariant
    enforced by tests.
    """
    if not error_message:
        return "other"
    haystack = error_message.lower()
    for needle, category in _TAXONOMY:
        if needle in haystack:
            return category
    return "other"
