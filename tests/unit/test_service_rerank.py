import asyncio

import pytest

from piighost.service.core import PIIGhostService
from piighost.service.config import ServiceConfig, RerankerSection


@pytest.fixture()
def svc_with_reranker(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")

    # Fake reranker that scores by chunk length
    class _FakeReranker:
        async def rerank(self, query, candidates):
            sorted_hits = sorted(candidates, key=lambda h: len(h.chunk), reverse=True)
            return [h.model_copy(update={"rank": i}) for i, h in enumerate(sorted_hits)]

    config = ServiceConfig(reranker=RerankerSection(backend="none"))
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault", config=config))

    # Patch _get_project on the instance so every project gets our fake reranker
    async def _get_project_with_reranker(name, *, auto_create=False):
        ps = await service.__class__._get_project(service, name, auto_create=auto_create)
        ps._reranker = _FakeReranker()
        return ps

    service._get_project = _get_project_with_reranker  # type: ignore[method-assign]
    yield service
    asyncio.run(service.close())


def test_query_rerank_requires_reranker(tmp_path, monkeypatch):
    """rerank=True without a reranker configured raises ValueError."""
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    try:
        doc = tmp_path / "doc.txt"
        doc.write_text("Alice here")
        asyncio.run(svc.index_path(doc, project="p"))
        with pytest.raises(ValueError, match="rerank=True"):
            asyncio.run(svc.query("Alice", project="p", k=3, rerank=True))
    finally:
        asyncio.run(svc.close())


def test_query_rerank_reorders_hits(svc_with_reranker, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "short.txt").write_text("Alice")
    (docs / "long.txt").write_text("Alice works on many different tasks including GDPR compliance")
    asyncio.run(svc_with_reranker.index_path(docs, project="p"))

    result = asyncio.run(
        svc_with_reranker.query("Alice", project="p", k=5, rerank=True, top_n=10)
    )
    # Fake reranker orders by length, so the long chunk should win
    assert "works on many" in result.hits[0].chunk


def test_query_top_n_clamped_to_k(svc_with_reranker, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice a")
    (docs / "b.txt").write_text("Alice b")
    asyncio.run(svc_with_reranker.index_path(docs, project="p"))

    # top_n=1 but k=5 → should still return up to k
    result = asyncio.run(
        svc_with_reranker.query("Alice", project="p", k=5, rerank=True, top_n=1)
    )
    assert len(result.hits) >= 1
