"""Curated regex packs for common PII by region.

Each constant is a ``dict[str, str]`` mapping an entity label to a regex
pattern. Pass them to :class:`~piighost.detector.RegexDetector` directly,
or merge several packs:

    from piighost.detector import RegexDetector
    from piighost.detector.patterns import FR_PATTERNS, GENERIC_PATTERNS

    detector = RegexDetector(patterns={**GENERIC_PATTERNS, **FR_PATTERNS})

Some patterns are syntactic only (IBAN, CREDIT_CARD, FR_NIR). Pair them
with the matching validator from :mod:`piighost.validators` to filter
out format-valid but checksum-invalid false positives.
"""

from piighost.detector.patterns._base import Pattern
from piighost.detector.patterns.credit_card import CREDIT_CARD_PATTERN
from piighost.detector.patterns.date import DATE_PATTERN
from piighost.detector.patterns.email import EMAIL_PATTERN
from piighost.detector.patterns.eu import EU_PATTERNS
from piighost.detector.patterns.fr import FR_PATTERNS
from piighost.detector.patterns.generic import GENERIC_PATTERNS
from piighost.detector.patterns.iban import IBAN_PATTERN
from piighost.detector.patterns.phone import PHONE_PATTERN
from piighost.detector.patterns.url import URL_PATTERN
from piighost.detector.patterns.us import US_PATTERNS
from piighost.detector.patterns.vat import VAT_PATTERN

# Re-introduced after the regional-pack refactor: list of Pattern objects
# consumed by RegexDetector when no explicit patterns argument is given.
# Order matters — national_id NIR/SIRET should precede CREDIT_CARD when
# enabled (see national_id.py); these are intentionally not in the default
# set because they need explicit Luhn validation.
DEFAULT_PATTERNS: list[Pattern] = [
    EMAIL_PATTERN,
    URL_PATTERN,
    PHONE_PATTERN,
    IBAN_PATTERN,
    VAT_PATTERN,
    DATE_PATTERN,
    CREDIT_CARD_PATTERN,
]

__all__ = [
    "DEFAULT_PATTERNS",
    "EU_PATTERNS",
    "FR_PATTERNS",
    "GENERIC_PATTERNS",
    "US_PATTERNS",
]
