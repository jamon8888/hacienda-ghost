from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

# Matches http:// and https:// URLs. The negative character class stops at
# whitespace and common HTML delimiters to avoid consuming surrounding text.
_URL_RE = re.compile(r"https?://[^\s<>\"']+")

URL_PATTERN = Pattern(
    label="URL",
    regex=_URL_RE,
)
