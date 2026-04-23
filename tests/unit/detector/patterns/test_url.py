from piighost.detector.patterns.url import URL_PATTERN


def test_matches_http_url():
    m = URL_PATTERN.regex.search("visit http://example.com today")
    assert m is not None
    assert m.group(0) == "http://example.com"


def test_matches_https_url_with_path():
    m = URL_PATTERN.regex.search("see https://piighost.eu/docs/api for details")
    assert m is not None
    assert m.group(0) == "https://piighost.eu/docs/api"


def test_no_match_bare_domain():
    m = URL_PATTERN.regex.search("visit example.com")
    assert m is None


def test_no_match_email():
    # email doesn't start with http(s)://
    m = URL_PATTERN.regex.search("contact alice@example.com")
    assert m is None


def test_url_label():
    assert URL_PATTERN.label == "URL"


def test_url_confidence():
    assert URL_PATTERN.confidence == 0.99


def test_strips_trailing_period():
    # In "see https://example.com." the period is sentence punctuation, not part of the URL.
    m = URL_PATTERN.regex.search("see https://example.com.")
    assert m is not None
    assert m.group(0) == "https://example.com"


def test_strips_trailing_comma():
    m = URL_PATTERN.regex.search("visit https://example.com/path, then close")
    assert m is not None
    assert m.group(0) == "https://example.com/path"


def test_preserves_url_with_query_string():
    # Query strings contain = and & which must not be stripped
    m = URL_PATTERN.regex.search("data at https://api.example.com/v1?key=abc&limit=10")
    assert m is not None
    assert m.group(0) == "https://api.example.com/v1?key=abc&limit=10"
