from __future__ import annotations

import re
from datetime import date

from piighost.detector.patterns._base import Pattern

_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[./\-]\d{1,2}[./\-]\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r")\b"
)


def _date_validator(text: str) -> bool:
    parts = re.split(r"[./\-]", text)
    if len(parts) != 3:
        return False
    try:
        if len(parts[0]) == 4:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        date(year, month, day)
        return True
    except (ValueError, IndexError):
        return False


DATE_PATTERN = Pattern(
    label="DATE_TIME",
    regex=_DATE_RE,
    validator=_date_validator,
)
