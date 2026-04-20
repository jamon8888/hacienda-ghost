from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_EU_COUNTRY_CODES = (
    "AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|GB|HR|HU|IE|IT|LT|LU|LV|"
    "MT|NL|PL|PT|RO|SE|SI|SK"
)

_VAT_RE = re.compile(
    rf"\b(?:{_EU_COUNTRY_CODES})[A-Z0-9]{{8,12}}\b"
)

VAT_PATTERN = Pattern(
    label="EU_VAT",
    regex=_VAT_RE,
)
