from piighost.detector.patterns.national_id import (
    FR_NIR_PATTERN,
    DE_PERSONALAUSWEIS_PATTERN,
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
