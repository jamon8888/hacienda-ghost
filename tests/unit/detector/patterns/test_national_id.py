from piighost.detector.patterns.national_id import (
    FR_NIR_PATTERN,
    DE_PERSONALAUSWEIS_PATTERN,
    FR_SIRET_PATTERN,
    FR_PASSPORT_PATTERN,
    FR_PERMIS_CONDUIRE_PATTERN,
    FR_NIF_PATTERN,
)


def test_fr_nir_matches_valid_format():
    m = FR_NIR_PATTERN.regex.search("NIR 1850578006048 30")
    assert m is not None


def test_fr_nir_validator_accepts_valid():
    # 185057800604830 (sex=1, year=85, month=05, dep=78, town=006, order=048, key=30)
    # key = 97 - (1850578006048 % 97) = 97 - 67 = 30
    assert FR_NIR_PATTERN.validator("185057800604830") is True


def test_fr_nir_validator_rejects_bad_key():
    assert FR_NIR_PATTERN.validator("185057800604899") is False


def test_fr_nir_validator_rejects_wrong_length():
    assert FR_NIR_PATTERN.validator("18505") is False


def test_fr_nir_label():
    assert FR_NIR_PATTERN.label == "FR_NIR"


def test_de_personalausweis_matches_format():
    m = DE_PERSONALAUSWEIS_PATTERN.regex.search("ID T22000129 valid")
    assert m is not None


def test_de_personalausweis_label():
    assert DE_PERSONALAUSWEIS_PATTERN.label == "DE_PERSONALAUSWEIS"


# ── FR_PERMIS_CONDUIRE ────────────────────────────────────────────────────────

def test_fr_permis_conduire_matches():
    m = FR_PERMIS_CONDUIRE_PATTERN.regex.search("permis no 07AB123456 valide")
    assert m is not None
    assert m.group(0) == "07AB123456"


def test_fr_permis_conduire_rejects_passport_biometric():
    # passport biometric has 5 trailing digits; DL requires 6 → no match
    m = FR_PERMIS_CONDUIRE_PATTERN.regex.search("09AA12345")
    assert m is None


def test_fr_permis_conduire_rejects_bare_letters():
    m = FR_PERMIS_CONDUIRE_PATTERN.regex.search("ABCDEFGHIJ")
    assert m is None


def test_fr_permis_conduire_label():
    assert FR_PERMIS_CONDUIRE_PATTERN.label == "FR_PERMIS_CONDUIRE"


def test_fr_permis_conduire_confidence():
    assert FR_PERMIS_CONDUIRE_PATTERN.confidence == 0.99


# ── FR_NIF ────────────────────────────────────────────────────────────────────

def test_fr_nif_matches_13_digits():
    m = FR_NIF_PATTERN.regex.search("NIF 1234567890123 fiscal")
    assert m is not None
    assert m.group(0) == "1234567890123"


def test_fr_nif_rejects_14_digits():
    # 14 digits → SIRET territory; word boundary prevents match
    m = FR_NIF_PATTERN.regex.search("55204944776279")
    assert m is None


def test_fr_nif_rejects_12_digits():
    m = FR_NIF_PATTERN.regex.search("123456789012")
    assert m is None


def test_fr_nif_label():
    assert FR_NIF_PATTERN.label == "FR_NIF"


def test_fr_nif_confidence():
    assert FR_NIF_PATTERN.confidence == 0.99
