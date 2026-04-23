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


def test_detector_finds_french_driving_licence():
    det = RegexDetector()
    hits = asyncio.run(det.detect("permis 07AB123456 valide"))
    assert any(d.label == "FR_PERMIS_CONDUIRE" for d in hits)


def test_detector_finds_french_nif():
    det = RegexDetector()
    hits = asyncio.run(det.detect("NIF fiscal 1234567890123"))
    assert any(d.label == "FR_NIF" for d in hits)


def test_detector_finds_url():
    det = RegexDetector()
    hits = asyncio.run(det.detect("profil https://linkedin.com/in/jean-dupont"))
    assert any(d.label == "URL" for d in hits)


def test_nif_wins_over_credit_card_for_13_digits():
    # A 13-digit number that also passes Luhn should be labelled FR_NIF,
    # not CREDIT_CARD, because FR_NIF is ordered before CREDIT_CARD.
    det = RegexDetector()
    hits = asyncio.run(det.detect("numéro fiscal 4532015112830"))  # 13-digit Luhn
    labels = [d.label for d in hits]
    assert "FR_NIF" in labels
    assert "CREDIT_CARD" not in labels
