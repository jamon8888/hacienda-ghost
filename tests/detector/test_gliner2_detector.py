"""Tests for Gliner2Detector hardware flags and batch inference.

Skipped automatically if gliner2 is not installed.
Uses MagicMock as the model object — Python does not enforce type annotations
at runtime, so any object with the right methods works.
"""
import pytest
from unittest.mock import MagicMock

pytest.importorskip("gliner2", reason="gliner2 not installed")

from piighost.detector.gliner2 import Gliner2Detector  # noqa: E402


def _make_model() -> MagicMock:
    """Return a mock GLiNER2 model with canned responses."""
    model = MagicMock()
    model.extract_entities.return_value = {
        "entities": {
            "person": [{"text": "Patrick", "start": 0, "end": 7, "confidence": 0.95}]
        }
    }
    model.batch_extract_entities.return_value = [
        {
            "entities": {
                "person": [{"text": "Patrick", "start": 0, "end": 7, "confidence": 0.95}]
            }
        },
        {
            "entities": {
                "person": [{"text": "Jean", "start": 0, "end": 4, "confidence": 0.90}]
            }
        },
    ]
    return model


def test_quantize_flag_calls_model_quantize() -> None:
    model = _make_model()
    Gliner2Detector(model=model, labels=["PERSON"], quantize=True)
    model.quantize.assert_called_once()


def test_compile_model_flag_calls_model_compile() -> None:
    model = _make_model()
    Gliner2Detector(model=model, labels=["PERSON"], compile_model=True)
    model.compile.assert_called_once()


def test_no_flags_does_not_call_quantize_or_compile() -> None:
    model = _make_model()
    Gliner2Detector(model=model, labels=["PERSON"])
    model.quantize.assert_not_called()
    model.compile.assert_not_called()


@pytest.mark.asyncio
async def test_detect_batch_returns_list_matching_inputs() -> None:
    model = _make_model()
    detector = Gliner2Detector(model=model, labels={"PERSON": "person"}, batch_size=8)

    texts = ["Patrick arrived.", "Jean departed."]
    results = await detector.detect_batch(texts)

    assert len(results) == 2
    assert all(isinstance(r, list) for r in results)
    assert results[0][0].text == "Patrick"
    assert results[1][0].text == "Jean"
    model.batch_extract_entities.assert_called_once_with(
        texts,
        entity_types=["person"],
        threshold=0.5,
        include_spans=True,
        include_confidence=True,
        batch_size=8,
    )


@pytest.mark.asyncio
async def test_detect_batch_single_matches_detect() -> None:
    model = _make_model()
    model.batch_extract_entities.return_value = [
        {
            "entities": {
                "person": [{"text": "Patrick", "start": 0, "end": 7, "confidence": 0.95}]
            }
        }
    ]
    detector = Gliner2Detector(model=model, labels={"PERSON": "person"})

    single = await detector.detect("Patrick arrived.")
    batch = await detector.detect_batch(["Patrick arrived."])

    assert len(single) == len(batch[0])
    assert single[0].text == batch[0][0].text
    assert single[0].label == batch[0][0].label


@pytest.mark.asyncio
async def test_detect_batch_empty_returns_empty() -> None:
    model = _make_model()
    detector = Gliner2Detector(model=model, labels=["PERSON"])
    result = await detector.detect_batch([])
    assert result == []
    model.batch_extract_entities.assert_not_called()
