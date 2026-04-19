"""PIIGhostDocumentAnonymizer replaces content and writes mapping to metadata."""

import json

import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
)


@pytest.mark.asyncio
async def test_atransform_anonymizes_and_stores_mapping(pipeline) -> None:
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    docs = [Document(page_content="Hello Alice", metadata={"source": "doc-1"})]

    out = await anonymizer.atransform_documents(docs)

    assert len(out) == 1
    assert "Alice" not in out[0].page_content
    mapping = json.loads(out[0].metadata["piighost_mapping"])
    assert any(item["original"] == "Alice" for item in mapping)


def test_transform_sync_path(pipeline) -> None:
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    docs = [Document(page_content="Hello Alice", metadata={"source": "doc-2"})]

    out = anonymizer.transform_documents(docs)

    assert "Alice" not in out[0].page_content


def test_counter_factory_rejected() -> None:
    from piighost.anonymizer import Anonymizer
    from piighost.models import Detection, Span
    from piighost.pipeline.thread import ThreadAnonymizationPipeline
    from piighost.placeholder import CounterPlaceholderFactory

    class _StubDetector:
        async def detect(self, text: str) -> list[Detection]:
            idx = text.find("Alice")
            if idx < 0:
                return []
            return [
                Detection(
                    text="Alice",
                    label="PERSON",
                    position=Span(start_pos=idx, end_pos=idx + len("Alice")),
                    confidence=1.0,
                )
            ]

    detector = _StubDetector()
    anon = Anonymizer(CounterPlaceholderFactory())
    bad_pipeline = ThreadAnonymizationPipeline(detector=detector, anonymizer=anon)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="HashPlaceholderFactory"):
        PIIGhostDocumentAnonymizer(pipeline=bad_pipeline)


def test_empty_content_is_skipped(pipeline) -> None:
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    docs = [Document(page_content="   ", metadata={"source": "doc-empty"})]

    out = anonymizer.transform_documents(docs)

    assert out[0].page_content == "   "
    assert "piighost_mapping" not in out[0].metadata
