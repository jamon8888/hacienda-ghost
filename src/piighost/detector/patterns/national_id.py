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

# SIRET: 14-digit French business identifier, validates with Luhn algorithm.
# Format: 9-digit SIREN + 5-digit NIC (e.g. 55204944776279).
_FR_SIRET_RE = re.compile(r"\b\d{14}\b")


def _fr_siret_validator(text: str) -> bool:
    digits = [int(c) for c in text if c.isdigit()]
    if len(digits) != 14:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# French passport: biometric (2 digits + 2 uppercase + 5 digits) or older
# formats with 2 uppercase letters followed by 6–7 digits.
_FR_PASSPORT_RE = re.compile(
    r"\b(?:\d{2}[A-Z]{2}\d{5}|[A-Z]{2}\d{6,7})\b"
)


DE_PERSONALAUSWEIS_PATTERN = Pattern(
    label="DE_PERSONALAUSWEIS",
    regex=_DE_ID_RE,
)

FR_NIR_PATTERN = Pattern(
    label="FR_NIR",
    regex=_FR_NIR_RE,
    validator=_fr_nir_validator,
)

FR_SIRET_PATTERN = Pattern(
    label="FR_SIRET",
    regex=_FR_SIRET_RE,
    validator=_fr_siret_validator,
)

FR_PASSPORT_PATTERN = Pattern(
    label="FR_PASSPORT",
    regex=_FR_PASSPORT_RE,
)

# French driving licence (EU-harmonised format, issued since ~2013).
# Format: 2 digits + 2 uppercase letters + 6 digits = 10 chars, e.g. 07AB123456.
# Deliberately distinct from FR_PASSPORT biometric (\d{2}[A-Z]{2}\d{5}, 9 chars).
# No public checksum algorithm exists; pattern length is the sole discriminator.
_FR_PERMIS_RE = re.compile(r"\b\d{2}[A-Z]{2}\d{6}\b")

FR_PERMIS_CONDUIRE_PATTERN = Pattern(
    label="FR_PERMIS_CONDUIRE",
    regex=_FR_PERMIS_RE,
)

# French individual tax identifier (numéro fiscal / SPI), always 13 digits.
# Must precede CREDIT_CARD in DEFAULT_PATTERNS: old 13-digit Visa cards also
# pass Luhn, but are vanishingly rare in French legal documents.
# Note: a standalone 13-digit NIR body (without its 2-digit key) would also
# match here and be labelled FR_NIF. In practice French legal documents always
# carry the full 15-digit NIR, so this collision is considered acceptable.
_FR_NIF_RE = re.compile(r"\b\d{13}\b")

FR_NIF_PATTERN = Pattern(
    label="FR_NIF",
    regex=_FR_NIF_RE,
)
