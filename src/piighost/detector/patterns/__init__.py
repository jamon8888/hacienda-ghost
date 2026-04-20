from __future__ import annotations

from piighost.detector.patterns._base import Pattern
from piighost.detector.patterns.credit_card import CREDIT_CARD_PATTERN
from piighost.detector.patterns.date import DATE_PATTERN
from piighost.detector.patterns.email import EMAIL_PATTERN
from piighost.detector.patterns.iban import IBAN_PATTERN
from piighost.detector.patterns.ip import IPV4_PATTERN, IPV6_PATTERN
from piighost.detector.patterns.national_id import (
    DE_PERSONALAUSWEIS_PATTERN,
    FR_NIR_PATTERN,
)
from piighost.detector.patterns.phone import PHONE_PATTERN
from piighost.detector.patterns.vat import VAT_PATTERN

DEFAULT_PATTERNS: list[Pattern] = [
    EMAIL_PATTERN,
    PHONE_PATTERN,
    IPV4_PATTERN,
    IPV6_PATTERN,
    CREDIT_CARD_PATTERN,
    IBAN_PATTERN,
    VAT_PATTERN,
    DATE_PATTERN,
    FR_NIR_PATTERN,
    DE_PERSONALAUSWEIS_PATTERN,
]
