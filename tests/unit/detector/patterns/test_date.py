from piighost.detector.patterns.date import DATE_PATTERN


def test_matches_slash_date():
    m = DATE_PATTERN.regex.search("born 15/03/1990 today")
    assert m is not None
    assert m.group(0) == "15/03/1990"


def test_matches_iso_date():
    m = DATE_PATTERN.regex.search("DOB 1990-03-15 confirmed")
    assert m is not None


def test_matches_dot_date():
    m = DATE_PATTERN.regex.search("Geburtsdatum 15.03.1990 ok")
    assert m is not None


def test_validator_rejects_invalid_month():
    assert DATE_PATTERN.validator("15/13/1990") is False


def test_validator_rejects_invalid_day():
    assert DATE_PATTERN.validator("32/01/1990") is False


def test_validator_accepts_leap_day():
    assert DATE_PATTERN.validator("29/02/2000") is True


def test_validator_rejects_non_leap_feb_29():
    assert DATE_PATTERN.validator("29/02/1999") is False


def test_label_is_date_time():
    assert DATE_PATTERN.label == "DATE_TIME"
