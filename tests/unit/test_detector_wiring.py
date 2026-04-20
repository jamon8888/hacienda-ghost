import asyncio
from piighost.service.config import ServiceConfig, DetectorSection
from piighost.service.core import _build_default_detector
from piighost.detector.regex import RegexDetector


def test_regex_only_backend_returns_regex_detector():
    config = ServiceConfig(detector=DetectorSection(backend="regex_only"))
    detector = asyncio.run(_build_default_detector(config))
    assert isinstance(detector, RegexDetector)


def test_regex_detector_detects_email():
    config = ServiceConfig(detector=DetectorSection(backend="regex_only"))
    detector = asyncio.run(_build_default_detector(config))
    detections = asyncio.run(detector.detect("contact alice@example.com"))
    assert any(d.label == "EMAIL_ADDRESS" for d in detections)
