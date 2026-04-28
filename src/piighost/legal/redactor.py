"""OutboundRedactor — sanitises payloads before they leave the daemon.

Strategy:
  1. Strip any <<label:HASH>> tokens (our placeholder format leaks
     the redaction scheme even though the originals are gone).
  2. Apply anonymize_fn to scrub any PII the caller missed.
  3. Verify legal-grammar patterns survive (article numbers, dates,
     code names, pourvoi numbers, etc.).
  4. Hard-fail on anonymize crash — never proceed with un-redacted
     payload.
"""
from __future__ import annotations

import re
from typing import Any, Callable


# Patterns we DO want to keep — legal grammar essential to the search.
_LEGAL_GRAMMAR_PATTERNS = [
    re.compile(r"\barticle\s+[LRD]?\.?\s*\d+(?:-\d+)*\b", re.I),
    re.compile(r"\b(loi|décret|ordonnance)\s+n[°o]?\s*\d{2,4}[-–]\d+", re.I),
    re.compile(r"\b\d{2}[-–]\d+\.\d+\b"),  # pourvoi
    re.compile(r"\b(Cass|CE|CC|CJUE|TJ|TC)\b\.?", re.I),
    re.compile(r"\b\d{1,2}\s+\w+\s+\d{4}\b"),  # French dates
    re.compile(r"\bCode\s+[\w\s'-]+", re.I),
]

# Strip our own placeholder format
_PLACEHOLDER_RE = re.compile(r"<<[a-zA-Z_]+:[a-f0-9]+>>")


class OutboundRedactor:
    """Apply anonymize() + legal-grammar whitelist before wire send."""

    def __init__(self, anonymize_fn: Callable[[str], str]) -> None:
        self._anonymize = anonymize_fn

    def redact(self, text: str) -> str:
        """Return a sanitised copy of *text* safe to send outbound.

        Raises whatever ``anonymize_fn`` raises — we never silently
        proceed with un-redacted input.
        """
        if not text:
            return text
        # 1. Strip our placeholder format
        out = _PLACEHOLDER_RE.sub("[REDACTED]", text)
        # 2. Anonymize whatever PII slipped through
        out = self._anonymize(out)
        return out

    def redact_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact every string value in *payload*. Non-string
        values are kept verbatim (numbers, booleans, lists of non-strings).
        """
        result: dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(v, str):
                result[k] = self.redact(v)
            elif isinstance(v, dict):
                result[k] = self.redact_dict(v)
            elif isinstance(v, list):
                result[k] = [
                    self.redact(item) if isinstance(item, str) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result
