"""E2E: Haystack RAG with filter + streaming."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("haystack")

from haystack import component

from piighost.integrations.haystack.rag import build_piighost_rag
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


@component
class _StreamingGen:
    def __init__(self) -> None:
        self.streaming_callback = None

    @component.output_types(replies=list[str])
    def run(self, prompt: str) -> dict:
        if self.streaming_callback is not None:
            try:
                from haystack.dataclasses import StreamingChunk
                for ch in "abc":
                    self.streaming_callback(StreamingChunk(content=ch))
            except ImportError:  # pragma: no cover
                pass
        return {"replies": ["abc"]}


def test_haystack_streaming_pipeline_runs(svc, tmp_path):
    captured: list[str] = []

    def cb(chunk):
        captured.append(getattr(chunk, "content", str(chunk)))

    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(doc, project="p"))

    gen = _StreamingGen()
    pipeline = build_piighost_rag(
        svc, project="p", llm_generator=gen, streaming_callback=cb
    )
    pipeline.run({"query_anonymizer": {"text": "Who?"}})
    assert "".join(captured) == "abc"
