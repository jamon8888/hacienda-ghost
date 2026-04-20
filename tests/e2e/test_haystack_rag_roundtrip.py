"""E2E: Haystack build_piighost_rag — pipeline ingest + run with fake generator, no PII leak."""

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
class _RecordingFakeGenerator:
    """Haystack Generator that records every prompt it receives."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    @component.output_types(replies=list[str])
    def run(self, prompt: str) -> dict:
        self.prompts.append(prompt)
        return {"replies": ["(fake reply)"]}


def test_haystack_rag_roundtrip(svc, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works in Paris on GDPR compliance contracts.")

    asyncio.run(svc.index_path(docs, project="client-a"))

    gen = _RecordingFakeGenerator()
    pipeline = build_piighost_rag(svc, project="client-a", llm_generator=gen)
    output = pipeline.run({"query_anonymizer": {"text": "Where does Alice work?"}})
    assert "rehydrator" in output


def test_haystack_rag_no_pii_leak_to_generator(svc, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works in Paris on GDPR compliance contracts.")

    asyncio.run(svc.index_path(docs, project="client-a"))

    gen = _RecordingFakeGenerator()
    pipeline = build_piighost_rag(svc, project="client-a", llm_generator=gen)
    pipeline.run({"query_anonymizer": {"text": "Alice in Paris?"}})

    assert gen.prompts, "fake generator received no prompt — test didn't exercise the path"
    for prompt in gen.prompts:
        assert "Alice" not in prompt, f"raw PII 'Alice' leaked to generator: {prompt!r}"
        assert "Paris" not in prompt, f"raw PII 'Paris' leaked to generator: {prompt!r}"
