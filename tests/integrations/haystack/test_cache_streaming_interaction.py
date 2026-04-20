"""Verify cache hit bypasses streaming generator entirely."""
import asyncio

import pytest

pytest.importorskip("haystack")
pytest.importorskip("aiocache")

from haystack import component

from piighost.integrations.haystack.rag import build_piighost_rag
from piighost.integrations.langchain.cache import RagCache
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


@component
class _StreamingCountingGenerator:
    """Generator that counts .run() invocations AND invokes streaming_callback."""

    def __init__(self) -> None:
        self.streaming_callback = None
        self.calls = 0

    @component.output_types(replies=list[str])
    def run(self, prompt: str) -> dict:
        self.calls += 1
        if self.streaming_callback is not None:
            try:
                from haystack.dataclasses import StreamingChunk
                self.streaming_callback(StreamingChunk(content="answer"))
            except ImportError:  # pragma: no cover
                self.streaming_callback("answer")
        return {"replies": ["answer"]}


def test_cache_hit_skips_streaming_callback(svc, tmp_path):
    """On a cache hit, the generator is never invoked → streaming callback not called."""
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(doc, project="p"))

    captured: list[str] = []

    def user_cb(chunk):
        captured.append(getattr(chunk, "content", str(chunk)))

    cache = RagCache(ttl=60)
    gen = _StreamingCountingGenerator()
    wrapper = build_piighost_rag(
        svc,
        project="p",
        llm_generator=gen,
        streaming_callback=user_cb,
        cache=cache,
    )
    inputs = {"query_anonymizer": {"text": "Who is Alice?"}}

    wrapper.run(inputs)
    first_calls = gen.calls
    first_captured = len(captured)

    wrapper.run(inputs)  # Cache hit — generator not invoked
    assert gen.calls == first_calls, "cache hit must not re-invoke generator"
    assert len(captured) == first_captured, "cache hit must not trigger streaming callback"
