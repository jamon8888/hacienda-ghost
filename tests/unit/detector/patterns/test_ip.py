from piighost.detector.patterns.ip import IPV4_PATTERN, IPV6_PATTERN


def test_ipv4_matches_address():
    m = IPV4_PATTERN.regex.search("server 192.168.1.1 up")
    assert m is not None
    assert m.group(0) == "192.168.1.1"


def test_ipv4_validator_rejects_out_of_range():
    assert IPV4_PATTERN.validator("256.1.2.3") is False


def test_ipv4_validator_accepts_zero():
    assert IPV4_PATTERN.validator("0.0.0.0") is True


def test_ipv4_validator_accepts_max():
    assert IPV4_PATTERN.validator("255.255.255.255") is True


def test_ipv6_matches_full_address():
    m = IPV6_PATTERN.regex.search("addr 2001:0db8:85a3:0000:0000:8a2e:0370:7334 is")
    assert m is not None


def test_ipv6_matches_compressed():
    m = IPV6_PATTERN.regex.search("loopback ::1 set")
    assert m is not None


def test_ipv4_label():
    assert IPV4_PATTERN.label == "IP_ADDRESS"


def test_ipv6_label():
    assert IPV6_PATTERN.label == "IP_ADDRESS"


def test_ipv6_matches_middle_compressed():
    m = IPV6_PATTERN.regex.search("addr 2001:db8::1 end")
    assert m is not None
    assert m.group(0) == "2001:db8::1"


def test_ipv6_matches_another_middle_compressed():
    m = IPV6_PATTERN.regex.search("connect fe80::abcd:1234 now")
    assert m is not None
    assert m.group(0) == "fe80::abcd:1234"
