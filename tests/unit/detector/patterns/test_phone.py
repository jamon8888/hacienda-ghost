from piighost.detector.patterns.phone import PHONE_PATTERN


def test_matches_french_mobile():
    m = PHONE_PATTERN.regex.search("call +33 6 12 34 56 78 tomorrow")
    assert m is not None
    assert "+33 6 12 34 56 78" in m.group(0)


def test_matches_german_number():
    m = PHONE_PATTERN.regex.search("Reach us at +49 30 12345678")
    assert m is not None
    assert "+49 30 12345678" in m.group(0)


def test_matches_uk_number():
    m = PHONE_PATTERN.regex.search("phone +44 20 7946 0958 now")
    assert m is not None


def test_rejects_plain_digits():
    assert PHONE_PATTERN.regex.search("1234567") is None


def test_validator_rejects_too_short():
    assert PHONE_PATTERN.validator is not None
    assert PHONE_PATTERN.validator("+33 1") is False


def test_validator_accepts_normal_length():
    assert PHONE_PATTERN.validator("+33 6 12 34 56 78") is True


def test_label_is_phone_number():
    assert PHONE_PATTERN.label == "PHONE_NUMBER"
