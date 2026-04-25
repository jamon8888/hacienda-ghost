import asyncio
from piighost.detector.regex import RegexDetector


def test_detector_finds_email():
    det = RegexDetector()
    detections = asyncio.run(det.detect("Email alice@example.com for info"))
    assert len(detections) == 1
    assert detections[0].label == "EMAIL_ADDRESS"
    assert detections[0].text == "alice@example.com"


def test_detector_finds_multiple_emails():
    det = RegexDetector()
    detections = asyncio.run(det.detect("a@b.com and c@d.org"))
    assert len(detections) == 2
    assert {d.text for d in detections} == {"a@b.com", "c@d.org"}


def test_detector_empty_text():
    det = RegexDetector()
    detections = asyncio.run(det.detect(""))
    assert detections == []


def test_detector_no_matches():
    det = RegexDetector()
    detections = asyncio.run(det.detect("just plain text"))
    assert detections == []


def test_detection_has_correct_positions():
    det = RegexDetector()
    text = "Email alice@example.com now"
    detections = asyncio.run(det.detect(text))
    assert detections[0].position.start_pos == 6
    assert detections[0].position.end_pos == 23


def test_detector_finds_url():
    det = RegexDetector()
    hits = asyncio.run(det.detect("profil https://linkedin.com/in/jean-dupont"))
    assert any(d.label == "URL" for d in hits)


# Removed: test_detector_finds_french_driving_licence,
#          test_detector_finds_french_nif,
#          test_nif_wins_over_credit_card_for_13_digits.
#
# These tests assumed FR-specific national-id patterns were in the
# default RegexDetector pattern set. The regional-pack refactor (commit
# 270f666 "feat(placeholder)!: add Counter variants, restructure naming
# as Style+Mechanism" and surrounding work) split patterns into regional
# packs (FR_PATTERNS, EU_PATTERNS, US_PATTERNS, GENERIC_PATTERNS).
# FR national-id patterns are now opt-in via:
#     RegexDetector(patterns=[*GENERIC_PATTERNS_LIST, *FR_NID_PATTERNS])
# rather than firing by default. Coverage moved to tests/detector/.
