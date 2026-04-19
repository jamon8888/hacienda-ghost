"""PIIGhostQueryAnonymizer is a Runnable[str, dict] and strict by default."""

import pytest

pytest.importorskip("langchain_core")

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostQueryAnonymizer,
)


def test_invoke_returns_query_and_entities(pipeline) -> None:
    anon = PIIGhostQueryAnonymizer(pipeline=pipeline)

    result = anon.invoke("Where is Alice?")

    assert "Alice" not in result["query"]
    assert any(e.label == "PERSON" for e in result["entities"])


@pytest.mark.asyncio
async def test_ainvoke_path(pipeline) -> None:
    anon = PIIGhostQueryAnonymizer(pipeline=pipeline)

    result = await anon.ainvoke("Where is Alice?")

    assert "Alice" not in result["query"]


def test_strict_raises_on_detector_failure(pipeline) -> None:
    class BrokenDetector:
        async def detect(self, text: str) -> list:
            raise RuntimeError("boom")

    pipeline._detector = BrokenDetector()
    anon = PIIGhostQueryAnonymizer(pipeline=pipeline)

    with pytest.raises(RuntimeError, match="boom"):
        anon.invoke("Where is Alice?")
