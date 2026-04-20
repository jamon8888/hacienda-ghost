from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_RE = re.compile(
    r"(?:"
    # Full 8-group
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"
    # Starts with :: (loopback, etc.)
    r"|::(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*)?"
    # Prefix::suffix — the common compressed form
    r"|(?:[0-9A-Fa-f]{1,4}:)+:(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*)?"
    r")"
)


def _ipv4_validator(text: str) -> bool:
    parts = text.split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


IPV4_PATTERN = Pattern(
    label="IP_ADDRESS",
    regex=_IPV4_RE,
    validator=_ipv4_validator,
)

IPV6_PATTERN = Pattern(
    label="IP_ADDRESS",
    regex=_IPV6_RE,
)
