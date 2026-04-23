from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_PHONE_RE = re.compile(
    r"(?:\+\d{1,3}(?:[ .\-]?\d{1,4}){2,6}"  # international: +33 6 12 34 56 78
    r"|\b0[1-9](?:[ .\-]?\d{2}){4}\b)"       # French national: 06 12 34 56 78
)


def _phone_validator(text: str) -> bool:
    digits = [c for c in text if c.isdigit()]
    return 7 <= len(digits) <= 15


PHONE_PATTERN = Pattern(
    label="PHONE_NUMBER",
    regex=_PHONE_RE,
    validator=_phone_validator,
)
