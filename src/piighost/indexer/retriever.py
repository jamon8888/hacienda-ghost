from __future__ import annotations

import pickle
from pathlib import Path


class BM25Index:
    def __init__(self, pkl_path: Path) -> None:
        self._pkl_path = pkl_path
        self._records: list[dict] = []
        self._bm25 = None

    def rebuild(self, records: list[dict]) -> None:
        from rank_bm25 import BM25Okapi

        self._records = records
        corpus = [r["chunk"].lower().split() for r in records]
        self._bm25 = BM25Okapi(corpus)
        self._pkl_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._pkl_path, "wb") as f:
            pickle.dump((self._records, self._bm25), f)

    def load(self) -> bool:
        if not self._pkl_path.exists():
            return False
        with open(self._pkl_path, "rb") as f:
            self._records, self._bm25 = pickle.load(f)
        return True

    def search(self, query: str, *, k: int = 5) -> list[tuple[str, float]]:
        if self._bm25 is None:
            return []
        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens)
        pairs = sorted(
            zip([r["chunk_id"] for r in self._records], scores),
            key=lambda x: x[1],
            reverse=True,
        )
        return [(cid, float(s)) for cid, s in pairs[:k] if s > 0]


def reciprocal_rank_fusion(
    bm25_hits: list[tuple[str, float]],
    vector_hits: list[tuple[str, float]],
    *,
    bm25_weight: float = 0.4,
    vector_weight: float = 0.6,
    rrf_k: int = 60,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rank, (cid, _) in enumerate(bm25_hits):
        scores[cid] = scores.get(cid, 0.0) + bm25_weight / (rrf_k + rank + 1)
    for rank, (cid, _) in enumerate(vector_hits):
        scores[cid] = scores.get(cid, 0.0) + vector_weight / (rrf_k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
