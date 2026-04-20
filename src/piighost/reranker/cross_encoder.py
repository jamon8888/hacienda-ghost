"""Cross-encoder reranker backed by sentence-transformers."""

from __future__ import annotations

import asyncio

from piighost.service.models import QueryHit


def _load_cross_encoder():
    from sentence_transformers import CrossEncoder
    return CrossEncoder


CrossEncoder = None  # type: ignore[assignment]  # set lazily on first use; monkeypatchable by tests


class CrossEncoderReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        global CrossEncoder
        if CrossEncoder is None:
            CrossEncoder = _load_cross_encoder()
        self._model = CrossEncoder(model_name)

    async def rerank(self, query: str, candidates: list[QueryHit]) -> list[QueryHit]:
        if not candidates:
            return []
        pairs = [(query, hit.chunk) for hit in candidates]
        scores = await asyncio.to_thread(self._model.predict, pairs)
        scored: list[QueryHit] = []
        for hit, score in zip(candidates, scores):
            scored.append(hit.model_copy(update={"score": float(score)}))
        scored.sort(key=lambda h: h.score, reverse=True)
        reranked: list[QueryHit] = []
        for i, hit in enumerate(scored):
            reranked.append(hit.model_copy(update={"rank": i}))
        return reranked
