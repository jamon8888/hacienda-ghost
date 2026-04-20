from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_FR_NIR_RE = re.compile(
    r"\b[12][\s]?\d{2}[\s]?(?:0[1-9]|1[0-2])[\s]?"
    r"(?:\d{2}|2[AB])[\s]?\d{3}[\s]?\d{3}[\s]?\d{2}\b"
)


def _fr_nir_validator(text: str) -> bool:
    normalized = "".join(c for c in text if c.isdigit() or c in "AB")
    if len(normalized) != 15:
        return False
    body = normalized[:13]
    key_str = normalized[13:]
    body_numeric = body.replace("2A", "19").replace("2B", "18")
    try:
        body_int = int(body_numeric)
        key = int(key_str)
    except ValueError:
        return False
    expected_key = 97 - (body_int % 97)
    return expected_key == key


_DE_ID_RE = re.compile(r"\b[A-Z]\d{8}\b")


DE_PERSONALAUSWEIS_PATTERN = Pattern(
    label="DE_PERSONALAUSWEIS",
    regex=_DE_ID_RE,
)

FR_NIR_PATTERN = Pattern(
    label="FR_NIR",
    regex=_FR_NIR_RE,
    validator=_fr_nir_validator,
)
