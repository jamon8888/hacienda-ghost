"""Reranker protocol."""

from __future__ import annotations

from typing import Protocol

from piighost.service.models import QueryHit


class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: list[QueryHit]
    ) -> list[QueryHit]:
        """Return candidates re-sorted by rerank score, highest first."""
