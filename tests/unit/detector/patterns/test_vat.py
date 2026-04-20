from piighost.detector.patterns.vat import VAT_PATTERN


def test_matches_french_vat():
    m = VAT_PATTERN.regex.search("VAT FR12345678901 applies")
    assert m is not None
    assert m.group(0) == "FR12345678901"


def test_matches_german_vat():
    m = VAT_PATTERN.regex.search("vendor DE123456789 registered")
    assert m is not None


def test_matches_uk_vat():
    m = VAT_PATTERN.regex.search("invoice GB123456789")
    assert m is not None


def test_does_not_match_invalid_prefix():
    assert VAT_PATTERN.regex.search("XY123456789") is None


def test_label_is_eu_vat():
    assert VAT_PATTERN.label == "EU_VAT"
