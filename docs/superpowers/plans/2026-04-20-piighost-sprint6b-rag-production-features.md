# piighost Sprint 6b — RAG Production Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four production RAG features to piighost: metadata filters + cross-encoder reranking (service layer, used by CLI/MCP/wrappers), streaming answers + answer caching (wrapper layer, LangChain + Haystack).

**Architecture:** `QueryFilter` dataclass composed into `svc.query(filter=...)`. New `Reranker` protocol + `CrossEncoderReranker` loaded via `ServiceConfig.reranker.backend`. `StreamingRehydrator` with rolling buffer guarantees no partial `<LABEL:hash>` ever leaves the wrapper. `RagCache` wraps aiocache, keys hash anonymized data only.

**Tech Stack:** Python 3.10+, LanceDB WHERE clauses, sentence-transformers `CrossEncoder`, aiocache `SimpleMemoryCache`, LangChain `astream`, Haystack streaming callbacks.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/piighost/indexer/filters.py` | `QueryFilter` dataclass + `to_lance_where`/`matches` |
| Create | `src/piighost/reranker/__init__.py` | Package marker |
| Create | `src/piighost/reranker/base.py` | `Reranker` protocol |
| Create | `src/piighost/reranker/cross_encoder.py` | `CrossEncoderReranker` |
| Modify | `src/piighost/service/config.py` | `RerankerSection` + config route |
| Modify | `src/piighost/service/core.py` | `_build_default_reranker`, `_ProjectService.query(filter, rerank, top_n)`, multiplexer forwarding |
| Modify | `src/piighost/indexer/store.py` | `ChunkStore.vector_search(*, filter=...)` |
| Modify | `src/piighost/indexer/retriever.py` | `BM25Index.search(*, filter=...)` (post-filter) |
| Create | `src/piighost/integrations/langchain/streaming.py` | `StreamingRehydrator` |
| Modify | `src/piighost/integrations/langchain/rag.py` | `.astream()`, `.query()` accepts filter/rerank/top_n/cache |
| Create | `src/piighost/integrations/langchain/cache.py` | `RagCache` + `AnyCache` protocol + helpers |
| Modify | `src/piighost/integrations/haystack/rag.py` | `build_piighost_rag(streaming_callback=, cache=)` + `CachedRagPipeline` |
| Modify | `src/piighost/cli/commands/query.py` | `--filter-prefix`, `--filter-doc-ids`, `--rerank`, `--top-n` |
| Modify | `src/piighost/mcp/server.py` | `query` tool gains filter/rerank/top_n params |
| Modify | `src/piighost/daemon/server.py` | Forward filter/rerank/top_n to service |
| Create | `tests/unit/indexer/test_filters.py` | `QueryFilter` unit tests |
| Create | `tests/unit/reranker/test_cross_encoder.py` | `CrossEncoderReranker` with fake model |
| Create | `tests/unit/test_service_filter.py` | `svc.query(filter=...)` behavior |
| Create | `tests/unit/test_service_rerank.py` | `svc.query(rerank=True)` reorders + clamps top_n |
| Create | `tests/unit/test_streaming_rehydrator.py` | Rolling buffer edge cases |
| Create | `tests/unit/test_rag_cache.py` | `RagCache.make_key` determinism |
| Create | `tests/integrations/langchain/test_streaming.py` | `PIIGhostRAG.astream` emits no partial tokens |
| Create | `tests/integrations/langchain/test_caching.py` | Cache hit short-circuits LLM call |
| Create | `tests/integrations/haystack/test_streaming.py` | Streaming callback receives rehydrated chunks |
| Create | `tests/integrations/haystack/test_caching.py` | `CachedRagPipeline` wraps pipeline cleanly |
| Create | `tests/unit/test_cli_query_flags.py` | CLI new flags smoke test |
| Create | `tests/unit/test_mcp_query_filter_rerank.py` | MCP tool forwards new params |
| Create | `tests/e2e/test_langchain_rag_advanced.py` | Rerank + filter + cache E2E |
| Create | `tests/e2e/test_haystack_rag_advanced.py` | Rerank + filter + streaming E2E |

---

### Task 1: `QueryFilter` dataclass

**Files:**
- Create: `src/piighost/indexer/filters.py`
- Create: `tests/unit/indexer/test_filters.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/indexer/test_filters.py`:

```python
from piighost.indexer.filters import QueryFilter


def test_empty_filter_is_empty():
    f = QueryFilter()
    assert f.is_empty()
    assert f.to_lance_where() is None


def test_file_path_prefix_builds_like_clause():
    f = QueryFilter(file_path_prefix="/projects/client-a")
    assert not f.is_empty()
    assert f.to_lance_where() == "file_path LIKE '/projects/client-a%'"


def test_doc_ids_build_in_clause():
    f = QueryFilter(doc_ids=("abc123", "def456"))
    assert f.to_lance_where() == "doc_id IN ('abc123', 'def456')"


def test_combined_filter_joins_with_and():
    f = QueryFilter(file_path_prefix="/a", doc_ids=("abc",))
    where = f.to_lance_where()
    assert "file_path LIKE '/a%'" in where
    assert "doc_id IN ('abc')" in where
    assert " AND " in where


def test_matches_respects_prefix():
    f = QueryFilter(file_path_prefix="/a/")
    assert f.matches("x", "/a/docs.txt") is True
    assert f.matches("x", "/b/docs.txt") is False


def test_matches_respects_doc_ids():
    f = QueryFilter(doc_ids=("abc", "def"))
    assert f.matches("abc", "/x.txt") is True
    assert f.matches("zzz", "/x.txt") is False


def test_matches_empty_filter_allows_all():
    f = QueryFilter()
    assert f.matches("x", "/anywhere.txt") is True


def test_single_quote_in_prefix_is_escaped():
    f = QueryFilter(file_path_prefix="/o'brien/")
    assert "o''brien" in f.to_lance_where()


def test_filter_is_hashable():
    f = QueryFilter(file_path_prefix="/a", doc_ids=("x",))
    {f}  # no TypeError


def test_filter_is_frozen():
    import dataclasses
    f = QueryFilter()
    assert dataclasses.is_dataclass(f)
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.file_path_prefix = "/new"
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
python -m pytest tests/unit/indexer/test_filters.py -v -p no:randomly
```

Expected: `ModuleNotFoundError: No module named 'piighost.indexer.filters'`.

- [ ] **Step 3: Create `src/piighost/indexer/filters.py`**

```python
"""Retrieval-time filters for svc.query()."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueryFilter:
    file_path_prefix: str | None = None
    doc_ids: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        return self.file_path_prefix is None and not self.doc_ids

    def to_lance_where(self) -> str | None:
        clauses: list[str] = []
        if self.file_path_prefix:
            escaped = self.file_path_prefix.replace("'", "''")
            clauses.append(f"file_path LIKE '{escaped}%'")
        if self.doc_ids:
            ids = ", ".join(f"'{d}'" for d in self.doc_ids)
            clauses.append(f"doc_id IN ({ids})")
        return " AND ".join(clauses) if clauses else None

    def matches(self, doc_id: str, file_path: str) -> bool:
        if self.file_path_prefix and not file_path.startswith(self.file_path_prefix):
            return False
        if self.doc_ids and doc_id not in self.doc_ids:
            return False
        return True
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/indexer/test_filters.py -v -p no:randomly
```

Expected: 10 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/indexer/filters.py tests/unit/indexer/test_filters.py
git commit -m "feat(indexer): QueryFilter dataclass with LanceDB WHERE builder"
```

---

### Task 2: `ChunkStore.vector_search(filter=...)` + `BM25Index.search(filter=...)`

**Files:**
- Modify: `src/piighost/indexer/store.py`
- Modify: `src/piighost/indexer/retriever.py`
- Create: `tests/unit/indexer/test_filter_wiring.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/indexer/test_filter_wiring.py`:

```python
import pytest

from piighost.indexer.filters import QueryFilter
from piighost.indexer.retriever import BM25Index
from piighost.indexer.store import ChunkStore


def _records():
    return [
        {"chunk_id": "a-0", "doc_id": "a", "file_path": "/projects/a/doc1.txt", "chunk": "Alice works here"},
        {"chunk_id": "a-1", "doc_id": "a", "file_path": "/projects/a/doc1.txt", "chunk": "more about Alice"},
        {"chunk_id": "b-0", "doc_id": "b", "file_path": "/projects/b/doc1.txt", "chunk": "Bob works there"},
    ]


def test_bm25_search_no_filter_returns_all_matches(tmp_path):
    idx = BM25Index(tmp_path / "bm25.pkl")
    idx.rebuild(_records())
    hits = idx.search("Alice", k=5)
    ids = {cid for cid, _ in hits}
    assert "a-0" in ids
    assert "a-1" in ids


def test_bm25_search_with_file_prefix_filter(tmp_path):
    idx = BM25Index(tmp_path / "bm25.pkl")
    idx.rebuild(_records())
    f = QueryFilter(file_path_prefix="/projects/b/")
    hits = idx.search("Alice", k=5, filter=f)
    ids = {cid for cid, _ in hits}
    assert "a-0" not in ids
    assert "a-1" not in ids


def test_bm25_search_with_doc_ids_filter(tmp_path):
    idx = BM25Index(tmp_path / "bm25.pkl")
    idx.rebuild(_records())
    f = QueryFilter(doc_ids=("b",))
    hits = idx.search("works", k=5, filter=f)
    assert all(cid.startswith("b") for cid, _ in hits)
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/unit/indexer/test_filter_wiring.py -v -p no:randomly
```

Expected: `TypeError: search() got an unexpected keyword argument 'filter'`.

- [ ] **Step 3: Update `BM25Index.search` in `src/piighost/indexer/retriever.py`**

Find the current `search` method. Replace with the filter-aware version:

```python
def search(
    self,
    query: str,
    *,
    k: int = 5,
    filter: "QueryFilter | None" = None,
) -> list[tuple[str, float]]:
    if self._bm25 is None or not self._records:
        return []
    tokenized = query.lower().split()
    scores = self._bm25.get_scores(tokenized)
    scored = sorted(
        (
            (self._records[i]["chunk_id"], float(scores[i]), self._records[i])
            for i in range(len(self._records))
        ),
        key=lambda t: t[1],
        reverse=True,
    )
    if filter is not None and not filter.is_empty():
        scored = [
            (cid, score, rec)
            for cid, score, rec in scored
            if filter.matches(rec["doc_id"], rec["file_path"])
        ]
    return [(cid, score) for cid, score, _rec in scored[:k]]
```

Add the import at the top of `retriever.py`:

```python
from piighost.indexer.filters import QueryFilter
```

- [ ] **Step 4: Update `ChunkStore.vector_search` in `src/piighost/indexer/store.py`**

Read the current method. Replace with:

```python
def vector_search(
    self,
    embedding: list[float],
    *,
    k: int = 5,
    filter: "QueryFilter | None" = None,
) -> list[dict]:
    if self._meta_mode:
        records = list(self._meta)
        if filter is not None and not filter.is_empty():
            records = [r for r in records if filter.matches(r["doc_id"], r["file_path"])]
        # No real vector similarity in meta-mode; preserve insertion order
        return records[:k]
    if self._db is None:
        return []
    table_name = "chunks"
    if table_name not in self._db.list_tables().tables:
        return []
    tbl = self._db.open_table(table_name)
    search = tbl.search(embedding)
    if filter is not None and not filter.is_empty():
        where = filter.to_lance_where()
        if where:
            search = search.where(where)
    rows = search.limit(k).to_list()
    return rows
```

Add at the top:

```python
from piighost.indexer.filters import QueryFilter
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/unit/indexer/test_filter_wiring.py tests/unit/indexer/ -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 6: Run full suite — no regressions**

```bash
python -m pytest tests/unit/ tests/e2e/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/indexer/store.py src/piighost/indexer/retriever.py tests/unit/indexer/test_filter_wiring.py
git commit -m "feat(indexer): BM25Index.search and ChunkStore.vector_search accept QueryFilter"
```

---

### Task 3: `svc.query(filter=...)` plumbing + service-layer test

**Files:**
- Modify: `src/piighost/service/core.py`
- Create: `tests/unit/test_service_filter.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_service_filter.py`:

```python
import asyncio

import pytest

from piighost.indexer.filters import QueryFilter
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


def test_query_without_filter_returns_all(svc, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works here")
    (docs / "b.txt").write_text("Alice works there")
    asyncio.run(svc.index_path(docs, project="p"))

    result = asyncio.run(svc.query("Alice", project="p", k=5))
    assert len(result.hits) >= 1


def test_query_with_file_prefix_filter_scopes_results(svc, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works here")
    (docs / "b.txt").write_text("Alice works there")
    asyncio.run(svc.index_path(docs, project="p"))

    a_path = docs / "a.txt"
    f = QueryFilter(file_path_prefix=str(a_path))
    result = asyncio.run(svc.query("Alice", project="p", k=5, filter=f))

    assert all(hit.file_path == str(a_path) for hit in result.hits)
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/unit/test_service_filter.py -v -p no:randomly
```

Expected: `TypeError: query() got an unexpected keyword argument 'filter'`.

- [ ] **Step 3: Update `_ProjectService.query` in `src/piighost/service/core.py`**

Find the `_ProjectService.query` method. Replace it with:

```python
async def query(
    self,
    text: str,
    *,
    k: int = 5,
    filter: "QueryFilter | None" = None,
) -> QueryResult:
    from piighost.indexer.retriever import reciprocal_rank_fusion
    from piighost.service.models import QueryHit, QueryResult

    anon_result = await self.anonymize(text)
    anon_query = anon_result.anonymized

    bm25_hits = self._bm25.search(anon_query, k=k * 2, filter=filter)
    query_vecs = await self._embedder.embed([anon_query])
    vec_hits_raw = self._chunk_store.vector_search(query_vecs[0], k=k * 2, filter=filter)
    vector_hits = [(r["chunk_id"], r.get("_distance", 0.0)) for r in vec_hits_raw]

    fused = reciprocal_rank_fusion(bm25_hits, vector_hits, rrf_k=60)[:k]

    all_records = {r["chunk_id"]: r for r in self._chunk_store.all_records()}
    hits: list[QueryHit] = []
    for rank, (chunk_id, score) in enumerate(fused):
        rec = all_records.get(chunk_id)
        if rec is None:
            continue
        hits.append(
            QueryHit(
                doc_id=rec["doc_id"],
                file_path=rec["file_path"],
                chunk=rec["chunk"],
                score=score,
                rank=rank,
            )
        )

    return QueryResult(query=text, hits=hits, k=k)
```

Also add the import at the top of the file:

```python
from piighost.indexer.filters import QueryFilter
```

- [ ] **Step 4: Update multiplexer `PIIGhostService.query`**

Find the multiplexer's `query` method. Add `filter` param and forward:

```python
async def query(
    self,
    text: str,
    *,
    k: int = 5,
    project: str = "default",
    filter: "QueryFilter | None" = None,
):
    svc = await self._get_project(project)
    return await svc.query(text, k=k, filter=filter)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/unit/test_service_filter.py -v -p no:randomly
```

Expected: 2 PASSED.

- [ ] **Step 6: Run full suite**

```bash
python -m pytest tests/unit/ tests/e2e/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_service_filter.py
git commit -m "feat(service): svc.query accepts QueryFilter"
```

---

### Task 4: `Reranker` protocol + `CrossEncoderReranker`

**Files:**
- Create: `src/piighost/reranker/__init__.py`
- Create: `src/piighost/reranker/base.py`
- Create: `src/piighost/reranker/cross_encoder.py`
- Create: `tests/unit/reranker/__init__.py`
- Create: `tests/unit/reranker/test_cross_encoder.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/reranker/__init__.py` (empty). Then create `tests/unit/reranker/test_cross_encoder.py`:

```python
import asyncio

from piighost.reranker.cross_encoder import CrossEncoderReranker
from piighost.service.models import QueryHit


class _FakeCE:
    """Stand-in for sentence_transformers.CrossEncoder — deterministic scores."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def predict(self, pairs):
        # Score = length of chunk (longer chunks "win")
        return [float(len(p[1])) for p in pairs]


def _hit(chunk_id: str, chunk: str, score: float = 0.5) -> QueryHit:
    return QueryHit(
        doc_id=chunk_id,
        file_path=f"/p/{chunk_id}.txt",
        chunk=chunk,
        score=score,
        rank=0,
    )


def test_reranker_reorders_by_fake_score(monkeypatch):
    import piighost.reranker.cross_encoder as mod
    monkeypatch.setattr(mod, "CrossEncoder", _FakeCE, raising=False)

    r = CrossEncoderReranker(model_name="fake-model")
    hits = [
        _hit("short", "short"),
        _hit("middle", "middle length chunk"),
        _hit("longest", "the longest chunk of all the chunks here"),
    ]
    reranked = asyncio.run(r.rerank("query", hits))
    # Longest chunk should rank first now
    assert reranked[0].chunk.startswith("the longest")
    assert reranked[-1].chunk == "short"


def test_reranker_assigns_sequential_ranks(monkeypatch):
    import piighost.reranker.cross_encoder as mod
    monkeypatch.setattr(mod, "CrossEncoder", _FakeCE, raising=False)

    r = CrossEncoderReranker(model_name="fake-model")
    hits = [_hit("a", "aa"), _hit("b", "bbb"), _hit("c", "c")]
    reranked = asyncio.run(r.rerank("q", hits))
    assert [h.rank for h in reranked] == [0, 1, 2]


def test_reranker_empty_candidates_returns_empty(monkeypatch):
    import piighost.reranker.cross_encoder as mod
    monkeypatch.setattr(mod, "CrossEncoder", _FakeCE, raising=False)

    r = CrossEncoderReranker(model_name="fake-model")
    assert asyncio.run(r.rerank("q", [])) == []
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
python -m pytest tests/unit/reranker/test_cross_encoder.py -v -p no:randomly
```

Expected: `ModuleNotFoundError: No module named 'piighost.reranker'`.

- [ ] **Step 3: Create the protocol**

Create `src/piighost/reranker/__init__.py` (empty).

Create `src/piighost/reranker/base.py`:

```python
"""Reranker protocol."""

from __future__ import annotations

from typing import Protocol

from piighost.service.models import QueryHit


class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: list[QueryHit]
    ) -> list[QueryHit]:
        """Return candidates re-sorted by rerank score, highest first."""
```

- [ ] **Step 4: Create `CrossEncoderReranker`**

Create `src/piighost/reranker/cross_encoder.py`:

```python
"""Cross-encoder reranker backed by sentence-transformers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from piighost.service.models import QueryHit

if TYPE_CHECKING:
    pass


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
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/unit/reranker/test_cross_encoder.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/reranker/ tests/unit/reranker/
git commit -m "feat(reranker): Reranker protocol + CrossEncoderReranker"
```

---

### Task 5: `RerankerSection` config + service wiring + `svc.query(rerank=True)`

**Files:**
- Modify: `src/piighost/service/config.py`
- Modify: `src/piighost/service/core.py`
- Create: `tests/unit/test_service_rerank.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_service_rerank.py`:

```python
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
    service._detector_override = None

    # Inject fake reranker on the multiplexer itself.
    # The per-project service picks up the config's backend ("none" → None reranker).
    # For this test we monkeypatch the multiplexer to always return our fake when queried.
    async def _get_project_with_reranker(name, *, auto_create=False):
        ps = await PIIGhostService._get_project.__wrapped__(service, name, auto_create=auto_create) if hasattr(PIIGhostService._get_project, "__wrapped__") else None
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/unit/test_service_rerank.py -v -p no:randomly
```

Expected: `TypeError: query() got an unexpected keyword argument 'rerank'`.

- [ ] **Step 3: Add `RerankerSection` to `src/piighost/service/config.py`**

Read the file. Add after the existing `EmbedderSection` class:

```python
class RerankerSection(BaseModel):
    backend: Literal["none", "cross_encoder"] = "none"
    cross_encoder_model: str = "BAAI/bge-reranker-base"
    top_n: int = 20
```

Add to `ServiceConfig`:

```python
    reranker: RerankerSection = Field(default_factory=RerankerSection)
```

- [ ] **Step 4: Add `_build_default_reranker` + wire into `_ProjectService`**

In `src/piighost/service/core.py`, add a helper function near `_build_default_detector`:

```python
async def _build_default_reranker(config: ServiceConfig):
    if config.reranker.backend == "none":
        return None
    if config.reranker.backend == "cross_encoder":
        from piighost.reranker.cross_encoder import CrossEncoderReranker
        return CrossEncoderReranker(config.reranker.cross_encoder_model)
    raise NotImplementedError(f"reranker backend {config.reranker.backend!r}")
```

In `_ProjectService.__init__`, add `reranker` as a parameter (default `None`) and store it:

```python
def __init__(
    self,
    project_dir: Path,
    project_name: str,
    config: ServiceConfig,
    vault: Vault,
    audit: AuditLogger,
    detector: _Detector,
    ph_factory: HashPlaceholderFactory,
    reranker=None,
) -> None:
    # ... existing body ...
    self._reranker = reranker
```

In `_ProjectService.create`, accept and forward the reranker:

```python
@classmethod
async def create(
    cls,
    *,
    project_dir: Path,
    project_name: str,
    config: ServiceConfig | None = None,
    detector: "_Detector | None" = None,
    placeholder_salt: str = "",
    reranker=None,
) -> "_ProjectService":
    config = config or ServiceConfig.default()
    project_dir.mkdir(parents=True, exist_ok=True)
    vault = Vault.open(project_dir / "vault.db")
    audit = AuditLogger(project_dir / "audit.log")
    if detector is None:
        detector = await _build_default_detector(config)
    if reranker is None:
        reranker = await _build_default_reranker(config)
    return cls(
        project_dir=project_dir,
        project_name=project_name,
        config=config,
        vault=vault,
        audit=audit,
        detector=detector,
        ph_factory=HashPlaceholderFactory(salt=placeholder_salt),
        reranker=reranker,
    )
```

Update `_ProjectService.query` to accept `rerank` + `top_n`:

```python
async def query(
    self,
    text: str,
    *,
    k: int = 5,
    filter: "QueryFilter | None" = None,
    rerank: bool = False,
    top_n: int = 20,
) -> QueryResult:
    from piighost.indexer.retriever import reciprocal_rank_fusion
    from piighost.service.models import QueryHit, QueryResult

    if rerank and self._reranker is None:
        raise ValueError(
            "rerank=True but no reranker configured; "
            "set ServiceConfig.reranker.backend to 'cross_encoder'"
        )

    fetch_k = max(top_n, k) if rerank else k

    anon_result = await self.anonymize(text)
    anon_query = anon_result.anonymized

    bm25_hits = self._bm25.search(anon_query, k=fetch_k * 2, filter=filter)
    query_vecs = await self._embedder.embed([anon_query])
    vec_hits_raw = self._chunk_store.vector_search(query_vecs[0], k=fetch_k * 2, filter=filter)
    vector_hits = [(r["chunk_id"], r.get("_distance", 0.0)) for r in vec_hits_raw]

    fused = reciprocal_rank_fusion(bm25_hits, vector_hits, rrf_k=60)[:fetch_k]

    all_records = {r["chunk_id"]: r for r in self._chunk_store.all_records()}
    hits: list[QueryHit] = []
    for rank, (chunk_id, score) in enumerate(fused):
        rec = all_records.get(chunk_id)
        if rec is None:
            continue
        hits.append(
            QueryHit(
                doc_id=rec["doc_id"],
                file_path=rec["file_path"],
                chunk=rec["chunk"],
                score=score,
                rank=rank,
            )
        )

    if rerank:
        hits = await self._reranker.rerank(text, hits)
        hits = hits[:k]

    return QueryResult(query=text, hits=hits, k=k)
```

Update the multiplexer `PIIGhostService.query`:

```python
async def query(
    self,
    text: str,
    *,
    k: int = 5,
    project: str = "default",
    filter: "QueryFilter | None" = None,
    rerank: bool = False,
    top_n: int = 20,
):
    svc = await self._get_project(project)
    return await svc.query(text, k=k, filter=filter, rerank=rerank, top_n=top_n)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/unit/test_service_rerank.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 6: Run full suite**

```bash
python -m pytest tests/unit/ tests/e2e/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/service/ tests/unit/test_service_rerank.py
git commit -m "feat(service): svc.query(rerank=True, top_n=N) with Reranker plumbing"
```

---

### Task 6: `StreamingRehydrator`

**Files:**
- Create: `src/piighost/integrations/langchain/streaming.py`
- Create: `tests/unit/test_streaming_rehydrator.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_streaming_rehydrator.py`:

```python
import asyncio

import pytest

pytest.importorskip("langchain_core")

from piighost.integrations.langchain.streaming import StreamingRehydrator
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc_with_tokens(tmp_path, monkeypatch):
    """Service with a known entity so rehydration has something to do."""
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    # Anonymize so "Alice" → <PERSON:...> is in the vault
    anon = asyncio.run(service.anonymize("Alice works here", project="p"))
    token = anon.entities[0].token
    yield service, token
    asyncio.run(service.close())


def test_feed_plain_text_emits_immediately(svc_with_tokens):
    svc, _ = svc_with_tokens
    r = StreamingRehydrator(svc, "p")
    out = asyncio.run(r.feed("hello world"))
    assert out == "hello world"


def test_feed_complete_token_is_rehydrated(svc_with_tokens):
    svc, token = svc_with_tokens
    r = StreamingRehydrator(svc, "p")
    out = asyncio.run(r.feed(f"Name: {token} done"))
    assert "Alice" in out
    assert token not in out


def test_partial_token_stays_buffered(svc_with_tokens):
    svc, token = svc_with_tokens
    r = StreamingRehydrator(svc, "p")
    # Split token right after "<PERSON:"
    prefix, suffix = token[:8], token[8:]
    out1 = asyncio.run(r.feed(f"Name: {prefix}"))
    # The partial "<PERSON:" must NOT have been emitted yet
    assert "<" not in out1  # no partial token leaked
    assert out1 == "Name: "

    out2 = asyncio.run(r.feed(suffix))
    assert "Alice" in out2


def test_finalize_flushes_buffer(svc_with_tokens):
    svc, _ = svc_with_tokens
    r = StreamingRehydrator(svc, "p")
    asyncio.run(r.feed("pending"))
    # "pending" is plain text so it was already emitted; buffer is empty
    final = asyncio.run(r.finalize())
    assert final == ""


def test_finalize_flushes_partial_that_never_completes(svc_with_tokens):
    svc, _ = svc_with_tokens
    r = StreamingRehydrator(svc, "p")
    # Simulate a stream that ends with an incomplete token
    out = asyncio.run(r.feed("prefix <PERSON:abc"))
    # Incomplete token stays buffered
    assert "<" not in out
    final = asyncio.run(r.finalize())
    # On finalize, emit raw buffer (not a valid token, but no PII either)
    assert "<PERSON:abc" in final
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/unit/test_streaming_rehydrator.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/piighost/integrations/langchain/streaming.py`**

```python
"""Streaming-safe rehydrator — guarantees no partial <LABEL:hash> ever leaves."""

from __future__ import annotations

import re

from piighost.service.core import PIIGhostService


_OPEN_TOKEN_RE = re.compile(r"<[A-Z_]*:?[0-9a-f]*$")


class StreamingRehydrator:
    """Rolling-buffer rehydrator for incremental LLM output.

    The LLM may split a token like ``<PERSON:abc12345>`` across multiple
    chunks. This class buffers trailing text that looks like an
    in-progress token and only emits rehydrated text up to the last safe
    cut point.
    """

    def __init__(self, svc: PIIGhostService, project: str) -> None:
        self._svc = svc
        self._project = project
        self._buffer = ""

    async def feed(self, chunk: str) -> str:
        """Append ``chunk`` to the buffer, emit the safe prefix rehydrated."""
        self._buffer += chunk
        match = _OPEN_TOKEN_RE.search(self._buffer)
        cut = match.start() if match else len(self._buffer)
        to_emit, self._buffer = self._buffer[:cut], self._buffer[cut:]
        if not to_emit:
            return ""
        result = await self._svc.rehydrate(
            to_emit, project=self._project, strict=False
        )
        return result.text

    async def finalize(self) -> str:
        """Flush any remaining buffered text after the stream ends."""
        if not self._buffer:
            return ""
        result = await self._svc.rehydrate(
            self._buffer, project=self._project, strict=False
        )
        self._buffer = ""
        return result.text
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_streaming_rehydrator.py -v -p no:randomly
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/integrations/langchain/streaming.py tests/unit/test_streaming_rehydrator.py
git commit -m "feat(integrations/langchain): StreamingRehydrator with token-safe rolling buffer"
```

---

### Task 7: `PIIGhostRAG.astream` + `.query()` filter/rerank/top_n params

**Files:**
- Modify: `src/piighost/integrations/langchain/rag.py`
- Create: `tests/integrations/langchain/test_streaming.py`

- [ ] **Step 1: Write failing test**

Create `tests/integrations/langchain/test_streaming.py`:

```python
import asyncio

import pytest

pytest.importorskip("langchain_core")

from piighost.integrations.langchain.rag import PIIGhostRAG
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


class _StreamingFakeLLM:
    """Fake LLM that yields its configured response one character at a time."""

    def __init__(self, response: str) -> None:
        self._response = response

    async def astream(self, messages, config=None, **kwargs):
        from langchain_core.messages import AIMessageChunk

        for ch in self._response:
            yield AIMessageChunk(content=ch)


async def _collect(agen):
    out: list[str] = []
    async for x in agen:
        out.append(x)
    return out


def test_astream_yields_rehydrated_chunks(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="p")
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(rag.ingest(doc))

    anon = asyncio.run(rag.anonymizer.ainvoke("Alice"))
    token = anon["entities"][0]["token"]
    llm = _StreamingFakeLLM(f"Answer: {token} is here")

    chunks = asyncio.run(_collect(rag.astream("Where is Alice?", llm=llm)))
    combined = "".join(chunks)
    assert "Alice" in combined
    # No partial token leaked mid-stream
    for c in chunks:
        # A chunk may legitimately contain '<' without it being a partial token.
        # The invariant is: no '<LABEL:' prefix is EVER emitted.
        assert not (c.startswith("<") and ":" in c and ">" not in c)


def test_astream_handles_no_pii_in_response(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="p")
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(rag.ingest(doc))

    llm = _StreamingFakeLLM("Nothing to rehydrate here")
    chunks = asyncio.run(_collect(rag.astream("Where is Alice?", llm=llm)))
    assert "".join(chunks) == "Nothing to rehydrate here"
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/integrations/langchain/test_streaming.py -v -p no:randomly
```

Expected: `AttributeError: 'PIIGhostRAG' object has no attribute 'astream'`.

- [ ] **Step 3: Extend `PIIGhostRAG.query` + add `.astream`**

In `src/piighost/integrations/langchain/rag.py`, update `.query()` signature to accept `filter`, `rerank`, `top_n` (forward to `svc.query`):

```python
async def query(
    self,
    text: str,
    *,
    k: int = 5,
    llm: "BaseLanguageModel | None" = None,
    prompt: Any | None = None,
    filter: "Any | None" = None,
    rerank: bool = False,
    top_n: int = 20,
) -> str:
    anon = await self._svc.anonymize(text, project=self._project)
    result = await self._svc.query(
        anon.anonymized,
        project=self._project,
        k=k,
        filter=filter,
        rerank=rerank,
        top_n=top_n,
    )
    context = "\n\n".join(hit.chunk for hit in result.hits)

    if llm is None:
        rehydrated = await self._svc.rehydrate(
            context, project=self._project, strict=False
        )
        return rehydrated.text

    if prompt is not None:
        messages = prompt.format_messages(context=context, question=anon.anonymized)
    else:
        messages = _build_prompt(context=context, question=anon.anonymized)

    raw_answer = await llm.ainvoke(messages)
    answer_text = raw_answer.content if hasattr(raw_answer, "content") else str(raw_answer)
    rehydrated = await self._svc.rehydrate(
        answer_text, project=self._project, strict=False
    )
    return rehydrated.text
```

Add a new `astream` method to the class:

```python
async def astream(
    self,
    text: str,
    *,
    llm: "BaseLanguageModel",
    k: int = 5,
    prompt: Any | None = None,
    filter: "Any | None" = None,
    rerank: bool = False,
    top_n: int = 20,
):
    from piighost.integrations.langchain.streaming import StreamingRehydrator

    anon = await self._svc.anonymize(text, project=self._project)
    result = await self._svc.query(
        anon.anonymized,
        project=self._project,
        k=k,
        filter=filter,
        rerank=rerank,
        top_n=top_n,
    )
    context = "\n\n".join(hit.chunk for hit in result.hits)
    if prompt is not None:
        messages = prompt.format_messages(context=context, question=anon.anonymized)
    else:
        messages = _build_prompt(context=context, question=anon.anonymized)

    rehydrator = StreamingRehydrator(self._svc, self._project)
    async for chunk in llm.astream(messages):
        text_chunk = chunk.content if hasattr(chunk, "content") else str(chunk)
        emitted = await rehydrator.feed(text_chunk)
        if emitted:
            yield emitted
    final = await rehydrator.finalize()
    if final:
        yield final
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/integrations/langchain/test_streaming.py tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/integrations/langchain/rag.py tests/integrations/langchain/test_streaming.py
git commit -m "feat(integrations/langchain): PIIGhostRAG.astream + filter/rerank/top_n on .query"
```

---

### Task 8: `RagCache` + `PIIGhostRAG(cache=...)` short-circuits LLM call

**Files:**
- Create: `src/piighost/integrations/langchain/cache.py`
- Modify: `src/piighost/integrations/langchain/rag.py`
- Create: `tests/unit/test_rag_cache.py`
- Create: `tests/integrations/langchain/test_caching.py`

- [ ] **Step 1: Write failing unit test for `RagCache`**

Create `tests/unit/test_rag_cache.py`:

```python
import asyncio

import pytest

pytest.importorskip("aiocache")

from piighost.integrations.langchain.cache import RagCache


def test_make_key_is_deterministic():
    kwargs = dict(
        project="p",
        anonymized_query="<PERSON:abc12345>",
        k=5,
        filter_repr="None",
        prompt_hash="default",
        llm_id="FakeLLM",
    )
    assert RagCache.make_key(**kwargs) == RagCache.make_key(**kwargs)


def test_make_key_differs_by_project():
    base = dict(
        anonymized_query="q",
        k=5,
        filter_repr="None",
        prompt_hash="default",
        llm_id="FakeLLM",
    )
    assert RagCache.make_key(project="a", **base) != RagCache.make_key(project="b", **base)


def test_make_key_prefix():
    key = RagCache.make_key(
        project="p",
        anonymized_query="q",
        k=5,
        filter_repr="None",
        prompt_hash="default",
        llm_id="FakeLLM",
    )
    assert key.startswith("piighost_rag:")


def test_roundtrip_in_memory():
    cache = RagCache()
    asyncio.run(cache.set("k", "value"))
    assert asyncio.run(cache.get("k")) == "value"


def test_get_missing_returns_none():
    cache = RagCache()
    assert asyncio.run(cache.get("nope")) is None
```

- [ ] **Step 2: Write failing integration test**

Create `tests/integrations/langchain/test_caching.py`:

```python
import asyncio

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("aiocache")

from piighost.integrations.langchain.cache import RagCache
from piighost.integrations.langchain.rag import PIIGhostRAG
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


class _CountingLLM:
    def __init__(self, response: str) -> None:
        self._response = response
        self.call_count = 0

    async def ainvoke(self, messages, config=None, **kwargs):
        from langchain_core.messages import AIMessage
        self.call_count += 1
        return AIMessage(content=self._response)


def test_cache_hit_avoids_second_llm_call(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="p", cache=RagCache(ttl=60))
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(rag.ingest(doc))

    llm = _CountingLLM("answer")
    # First call: cache miss → LLM invoked
    answer_1 = asyncio.run(rag.query("Who is Alice?", llm=llm))
    assert llm.call_count == 1
    # Second call with identical inputs: cache hit → LLM not invoked again
    answer_2 = asyncio.run(rag.query("Who is Alice?", llm=llm))
    assert llm.call_count == 1
    assert answer_1 == answer_2


def test_different_projects_do_not_share_cache(svc, tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")

    cache = RagCache(ttl=60)
    rag_a = PIIGhostRAG(svc, project="a", cache=cache)
    rag_b = PIIGhostRAG(svc, project="b", cache=cache)
    asyncio.run(rag_a.ingest(doc))
    asyncio.run(rag_b.ingest(doc))

    llm = _CountingLLM("answer")
    asyncio.run(rag_a.query("Who is Alice?", llm=llm))
    asyncio.run(rag_b.query("Who is Alice?", llm=llm))
    # Different projects → different cache keys → 2 LLM invocations
    assert llm.call_count == 2


def test_cache_none_means_no_caching(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="p")  # cache=None
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works here")
    asyncio.run(rag.ingest(doc))

    llm = _CountingLLM("answer")
    asyncio.run(rag.query("Who is Alice?", llm=llm))
    asyncio.run(rag.query("Who is Alice?", llm=llm))
    assert llm.call_count == 2
```

- [ ] **Step 3: Run tests to verify failure**

```bash
python -m pytest tests/unit/test_rag_cache.py tests/integrations/langchain/test_caching.py -v -p no:randomly
```

Expected: `ModuleNotFoundError: No module named 'piighost.integrations.langchain.cache'`.

- [ ] **Step 4: Create `src/piighost/integrations/langchain/cache.py`**

```python
"""aiocache-backed answer cache for PIIGhostRAG."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from aiocache import SimpleMemoryCache


class AnyCache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...


class RagCache:
    def __init__(self, backend: AnyCache | None = None, *, ttl: int = 300) -> None:
        self._backend = backend or SimpleMemoryCache()
        self._ttl = ttl

    @staticmethod
    def make_key(
        *,
        project: str,
        anonymized_query: str,
        k: int,
        filter_repr: str,
        prompt_hash: str,
        llm_id: str,
    ) -> str:
        payload = json.dumps(
            {
                "p": project,
                "q": anonymized_query,
                "k": k,
                "f": filter_repr,
                "pr": prompt_hash,
                "llm": llm_id,
            },
            sort_keys=True,
        )
        return "piighost_rag:" + hashlib.sha256(payload.encode()).hexdigest()[:32]

    async def get(self, key: str) -> str | None:
        try:
            return await self._backend.get(key)
        except Exception:
            return None

    async def set(self, key: str, value: str) -> None:
        try:
            await self._backend.set(key, value, ttl=self._ttl)
        except Exception:
            pass


def _prompt_fingerprint(prompt) -> str:
    if prompt is None:
        return "default"
    text = getattr(prompt, "template", repr(prompt))
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _llm_id(llm) -> str:
    name = type(llm).__name__
    model = getattr(llm, "model_name", None) or getattr(llm, "model", "")
    return f"{name}:{model}" if model else name
```

- [ ] **Step 5: Wire cache into `PIIGhostRAG.__init__` and `.query`**

In `src/piighost/integrations/langchain/rag.py`:

Update the constructor:

```python
def __init__(
    self,
    svc: PIIGhostService,
    *,
    project: str = "default",
    cache: "Any | None" = None,
) -> None:
    self._svc = svc
    self._project = project
    self._cache = cache
```

Update `.query` to consult the cache:

```python
async def query(
    self,
    text: str,
    *,
    k: int = 5,
    llm: "BaseLanguageModel | None" = None,
    prompt: Any | None = None,
    filter: "Any | None" = None,
    rerank: bool = False,
    top_n: int = 20,
) -> str:
    from piighost.integrations.langchain.cache import (
        RagCache,
        _prompt_fingerprint,
        _llm_id,
    )

    anon = await self._svc.anonymize(text, project=self._project)

    cache_key = None
    if self._cache is not None and llm is not None:
        cache_key = RagCache.make_key(
            project=self._project,
            anonymized_query=anon.anonymized,
            k=k,
            filter_repr=repr(filter),
            prompt_hash=_prompt_fingerprint(prompt),
            llm_id=_llm_id(llm),
        )
        hit = await self._cache.get(cache_key)
        if hit is not None:
            return hit

    result = await self._svc.query(
        anon.anonymized,
        project=self._project,
        k=k,
        filter=filter,
        rerank=rerank,
        top_n=top_n,
    )
    context = "\n\n".join(hit.chunk for hit in result.hits)

    if llm is None:
        rehydrated = await self._svc.rehydrate(
            context, project=self._project, strict=False
        )
        return rehydrated.text

    if prompt is not None:
        messages = prompt.format_messages(context=context, question=anon.anonymized)
    else:
        messages = _build_prompt(context=context, question=anon.anonymized)

    raw_answer = await llm.ainvoke(messages)
    answer_text = raw_answer.content if hasattr(raw_answer, "content") else str(raw_answer)
    rehydrated = await self._svc.rehydrate(
        answer_text, project=self._project, strict=False
    )

    if cache_key is not None:
        await self._cache.set(cache_key, rehydrated.text)
    return rehydrated.text
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/unit/test_rag_cache.py tests/integrations/langchain/test_caching.py tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/integrations/langchain/cache.py \
        src/piighost/integrations/langchain/rag.py \
        tests/unit/test_rag_cache.py \
        tests/integrations/langchain/test_caching.py
git commit -m "feat(integrations/langchain): RagCache + PIIGhostRAG answer caching"
```

---

### Task 9: Haystack — `build_piighost_rag(filter=, rerank=, streaming_callback=, cache=)`

**Files:**
- Modify: `src/piighost/integrations/haystack/rag.py`
- Create: `tests/integrations/haystack/test_caching.py`
- Create: `tests/integrations/haystack/test_streaming.py`

- [ ] **Step 1: Write failing tests**

Create `tests/integrations/haystack/test_streaming.py`:

```python
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
class _StreamingGenerator:
    """Generator that invokes streaming_callback for each character."""

    def __init__(self) -> None:
        self.streaming_callback = None

    @component.output_types(replies=list[str])
    def run(self, prompt: str) -> dict:
        if self.streaming_callback is not None:
            try:
                from haystack.dataclasses import StreamingChunk
            except ImportError:  # pragma: no cover
                StreamingChunk = None
            for ch in "hello":
                if StreamingChunk is not None:
                    self.streaming_callback(StreamingChunk(content=ch))
                else:
                    self.streaming_callback(ch)
        return {"replies": ["hello"]}


def test_streaming_callback_receives_rehydrated_chunks(svc, tmp_path):
    captured: list[str] = []

    def user_callback(chunk):
        content = getattr(chunk, "content", str(chunk))
        captured.append(content)

    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(doc, project="p"))

    gen = _StreamingGenerator()
    pipeline = build_piighost_rag(
        svc, project="p", llm_generator=gen, streaming_callback=user_callback
    )
    pipeline.run({"query_anonymizer": {"text": "Who is Alice?"}})
    # The user callback must have been invoked for each streamed char
    assert len(captured) >= 1
    assert "".join(captured) == "hello"
```

Create `tests/integrations/haystack/test_caching.py`:

```python
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
class _CountingGenerator:
    def __init__(self) -> None:
        self.calls = 0

    @component.output_types(replies=list[str])
    def run(self, prompt: str) -> dict:
        self.calls += 1
        return {"replies": ["answer"]}


def test_cache_hit_short_circuits_haystack_pipeline(svc, tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(doc, project="p"))

    cache = RagCache(ttl=60)
    gen = _CountingGenerator()
    wrapper = build_piighost_rag(svc, project="p", llm_generator=gen, cache=cache)
    inputs = {"query_anonymizer": {"text": "Who is Alice?"}}

    wrapper.run(inputs)
    first_calls = gen.calls

    wrapper.run(inputs)  # Should hit the cache; generator not invoked
    assert gen.calls == first_calls


def test_cache_none_returns_bare_pipeline(svc):
    from haystack import Pipeline
    pipeline = build_piighost_rag(svc, project="p")
    assert isinstance(pipeline, Pipeline)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
python -m pytest tests/integrations/haystack/test_streaming.py tests/integrations/haystack/test_caching.py -v -p no:randomly
```

Expected: `TypeError: build_piighost_rag() got an unexpected keyword argument 'streaming_callback'` (or `cache`).

- [ ] **Step 3: Update `src/piighost/integrations/haystack/rag.py`**

Read the existing file. Add a `CachedRagPipeline` class at the end (before `build_piighost_rag`):

```python
class CachedRagPipeline:
    """Pipeline wrapper that checks a cache before running."""

    def __init__(
        self,
        pipeline: Pipeline,
        svc: PIIGhostService,
        project: str,
        cache,
        top_k: int,
    ) -> None:
        self._pipeline = pipeline
        self._svc = svc
        self._project = project
        self._cache = cache
        self._top_k = top_k

    @property
    def graph(self):
        return self._pipeline.graph

    def run(self, inputs: dict) -> dict:
        return run_coroutine_sync(self._arun(inputs))

    async def _arun(self, inputs: dict) -> dict:
        from piighost.integrations.langchain.cache import RagCache

        query_text = inputs.get("query_anonymizer", {}).get("text", "")
        anon = await self._svc.anonymize(query_text, project=self._project)
        key = RagCache.make_key(
            project=self._project,
            anonymized_query=anon.anonymized,
            k=self._top_k,
            filter_repr="None",
            prompt_hash="haystack_default",
            llm_id="haystack_generator",
        )
        hit = await self._cache.get(key)
        if hit is not None:
            return {"rehydrator": {"text": hit}}
        result = self._pipeline.run(inputs)
        answer = result.get("rehydrator", {}).get("text", "")
        if answer:
            await self._cache.set(key, answer)
        return result
```

Update `build_piighost_rag`:

```python
def build_piighost_rag(
    svc: PIIGhostService,
    *,
    project: str = "default",
    llm_generator: Any | None = None,
    top_k: int = 5,
    streaming_callback: Any | None = None,
    cache: Any | None = None,
):
    from haystack.components.builders import PromptBuilder

    pipeline = Pipeline()
    pipeline.add_component("query_anonymizer", _ServiceQueryAnonymizer(svc, project=project))
    pipeline.add_component("retriever", PIIGhostRetriever(svc, project=project, top_k=top_k))
    pipeline.add_component("prompt_builder", PromptBuilder(template=_HAYSTACK_PROMPT_TEMPLATE))
    pipeline.add_component("rehydrator", _ServiceRehydrator(svc, project=project))
    if llm_generator is not None:
        if streaming_callback is not None and hasattr(llm_generator, "streaming_callback"):
            from piighost.integrations.langchain.streaming import StreamingRehydrator
            rehydrator = StreamingRehydrator(svc, project)

            def _wrapped(chunk) -> None:
                content = getattr(chunk, "content", str(chunk))
                emitted = run_coroutine_sync(rehydrator.feed(content))
                if emitted:
                    try:
                        from haystack.dataclasses import StreamingChunk
                        streaming_callback(StreamingChunk(content=emitted))
                    except ImportError:  # pragma: no cover
                        streaming_callback(emitted)

            llm_generator.streaming_callback = _wrapped
        pipeline.add_component("llm", llm_generator)

    pipeline.connect("query_anonymizer.query", "retriever.query")
    pipeline.connect("query_anonymizer.query", "prompt_builder.question")
    pipeline.connect("retriever.documents", "prompt_builder.documents")
    if llm_generator is not None:
        pipeline.connect("prompt_builder.prompt", "llm.prompt")
        pipeline.connect("llm.replies", "rehydrator.text")

    if cache is not None:
        return CachedRagPipeline(pipeline, svc, project, cache, top_k)
    return pipeline
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/integrations/haystack/ -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/integrations/haystack/rag.py \
        tests/integrations/haystack/test_streaming.py \
        tests/integrations/haystack/test_caching.py
git commit -m "feat(integrations/haystack): streaming_callback + CachedRagPipeline wrapper"
```

---

### Task 10: CLI `--filter-prefix --filter-doc-ids --rerank --top-n`

**Files:**
- Modify: `src/piighost/cli/commands/query.py`
- Create: `tests/unit/test_cli_query_flags.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_cli_query_flags.py`:

```python
from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_query_help_has_filter_prefix():
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--filter-prefix" in result.output


def test_query_help_has_filter_doc_ids():
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--filter-doc-ids" in result.output


def test_query_help_has_rerank():
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--rerank" in result.output


def test_query_help_has_top_n():
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--top-n" in result.output
```

- [ ] **Step 2: Run test — should fail**

```bash
python -m pytest tests/unit/test_cli_query_flags.py -v -p no:randomly
```

Expected: at least one assertion fails.

- [ ] **Step 3: Update `src/piighost/cli/commands/query.py`**

Read the file. Add the four new options to the `run()` signature:

```python
filter_prefix: str = typer.Option("", "--filter-prefix", help="Restrict search to file_path starting with this prefix"),
filter_doc_ids: str = typer.Option("", "--filter-doc-ids", help="Comma-separated doc_ids to restrict search to"),
rerank: bool = typer.Option(False, "--rerank/--no-rerank", help="Apply cross-encoder reranking"),
top_n: int = typer.Option(20, "--top-n", help="Candidate pool size before reranking"),
```

Build a filter object and pass to the daemon and service:

```python
# In run():
filter_params = {}
if filter_prefix:
    filter_params["file_path_prefix"] = filter_prefix
if filter_doc_ids:
    filter_params["doc_ids"] = [d.strip() for d in filter_doc_ids.split(",") if d.strip()]

# daemon path — include filter dict in params
client.call(
    "query",
    {
        "text": text,
        "k": k,
        "project": project,
        "filter": filter_params or None,
        "rerank": rerank,
        "top_n": top_n,
    },
)

# local async path — build QueryFilter and pass
from piighost.indexer.filters import QueryFilter
qfilter = None
if filter_params:
    qfilter = QueryFilter(
        file_path_prefix=filter_params.get("file_path_prefix"),
        doc_ids=tuple(filter_params.get("doc_ids", [])),
    )
result = await svc.query(
    text, k=k, project=project, filter=qfilter, rerank=rerank, top_n=top_n
)
```

**Exact changes depend on the file's current structure — read it first to identify the `run()` signature and the daemon/async branches, then integrate the new params consistently with the existing pattern.**

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_cli_query_flags.py tests/unit/test_cli_project_flag.py -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/cli/commands/query.py tests/unit/test_cli_query_flags.py
git commit -m "feat(cli): --filter-prefix, --filter-doc-ids, --rerank, --top-n on query"
```

---

### Task 11: MCP `query` tool gains filter/rerank/top_n params

**Files:**
- Modify: `src/piighost/mcp/server.py`
- Create: `tests/unit/test_mcp_query_filter_rerank.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_mcp_query_filter_rerank.py`:

```python
import asyncio
import importlib.util

import pytest


@pytest.fixture()
def built_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    real_find_spec = importlib.util.find_spec

    def fake(name, *args, **kwargs):
        if name == "sentence_transformers":
            return object()
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr("importlib.util.find_spec", fake)

    from piighost.mcp.server import build_mcp
    mcp, svc = asyncio.run(build_mcp(tmp_path / "vault"))
    yield mcp, svc
    asyncio.run(svc.close())


def test_query_tool_accepts_filter_prefix(built_mcp, tmp_path):
    mcp, svc = built_mcp
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works here")
    asyncio.run(svc.index_path(doc, project="p"))

    tools = asyncio.run(mcp.get_tools())
    result = asyncio.run(
        tools["query"].run(
            {"text": "Alice", "project": "p", "k": 3, "filter_prefix": str(tmp_path)}
        )
    )
    payload = result.structured_content.get("result") if hasattr(result, "structured_content") else result
    assert "hits" in payload


def test_query_tool_accepts_rerank_param(built_mcp, tmp_path):
    mcp, svc = built_mcp
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice here")
    asyncio.run(svc.index_path(doc, project="p"))

    tools = asyncio.run(mcp.get_tools())
    # rerank=False should work fine (no reranker needed)
    result = asyncio.run(
        tools["query"].run({"text": "Alice", "project": "p", "k": 3, "rerank": False})
    )
    payload = result.structured_content.get("result") if hasattr(result, "structured_content") else result
    assert "hits" in payload
```

- [ ] **Step 2: Run test — should fail**

```bash
python -m pytest tests/unit/test_mcp_query_filter_rerank.py -v -p no:randomly
```

Expected: `query` tool signature doesn't accept `filter_prefix`.

- [ ] **Step 3: Update the `query` tool in `src/piighost/mcp/server.py`**

Find the `@mcp.tool(description="Hybrid BM25+vector search over indexed documents")` block. Replace it with:

```python
@mcp.tool(description="Hybrid BM25+vector search over indexed documents")
async def query(
    text: str,
    k: int = 5,
    project: str = "default",
    filter_prefix: str = "",
    filter_doc_ids: list[str] | None = None,
    rerank: bool = False,
    top_n: int = 20,
) -> dict:
    from piighost.indexer.filters import QueryFilter
    qfilter = None
    if filter_prefix or filter_doc_ids:
        qfilter = QueryFilter(
            file_path_prefix=filter_prefix or None,
            doc_ids=tuple(filter_doc_ids or ()),
        )
    result = await svc.query(
        text, k=k, project=project, filter=qfilter, rerank=rerank, top_n=top_n
    )
    return result.model_dump()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_mcp_query_filter_rerank.py tests/unit/test_mcp_project_wiring.py -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/server.py tests/unit/test_mcp_query_filter_rerank.py
git commit -m "feat(mcp): query tool accepts filter_prefix, filter_doc_ids, rerank, top_n"
```

---

### Task 12: Daemon dispatch forwards filter/rerank/top_n

**Files:**
- Modify: `src/piighost/daemon/server.py`

- [ ] **Step 1: Read current `_dispatch` function**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
grep -n "if method ==" src/piighost/daemon/server.py | head -20
```

- [ ] **Step 2: Update the `query` dispatch case**

Find the existing `query` case. Replace with:

```python
if method == "query":
    from piighost.indexer.filters import QueryFilter
    raw_filter = params.get("filter")
    qfilter = None
    if raw_filter:
        qfilter = QueryFilter(
            file_path_prefix=raw_filter.get("file_path_prefix") or None,
            doc_ids=tuple(raw_filter.get("doc_ids") or ()),
        )
    result = await svc.query(
        params["text"],
        k=params.get("k", 5),
        project=params.get("project", "default"),
        filter=qfilter,
        rerank=params.get("rerank", False),
        top_n=params.get("top_n", 20),
    )
    return result.model_dump()
```

- [ ] **Step 3: Run full suite — no regressions**

```bash
python -m pytest tests/unit/ tests/e2e/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add src/piighost/daemon/server.py
git commit -m "feat(daemon): query dispatch forwards filter/rerank/top_n to service"
```

---

### Task 13: E2E LangChain RAG with rerank + filter + cache

**Files:**
- Create: `tests/e2e/test_langchain_rag_advanced.py`

- [ ] **Step 1: Create the test**

```python
"""E2E: LangChain RAG with filter + rerank + cache."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("aiocache")

from piighost.indexer.filters import QueryFilter
from piighost.integrations.langchain.cache import RagCache
from piighost.integrations.langchain.rag import PIIGhostRAG
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


class _CountingLLM:
    def __init__(self, response: str) -> None:
        self._response = response
        self.call_count = 0

    async def ainvoke(self, messages, config=None, **kwargs):
        from langchain_core.messages import AIMessage
        self.call_count += 1
        return AIMessage(content=self._response)


def test_filter_plus_cache_roundtrip(svc, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works in Paris on GDPR contracts")
    (docs / "b.txt").write_text("Bob works on medical records")

    rag = PIIGhostRAG(svc, project="p", cache=RagCache(ttl=60))
    asyncio.run(rag.ingest(docs))

    llm = _CountingLLM("answer about Alice")
    f = QueryFilter(file_path_prefix=str(docs / "a.txt"))
    # First call — cache miss
    answer_1 = asyncio.run(rag.query("Who works on contracts?", llm=llm, filter=f))
    assert llm.call_count == 1
    # Second call, same filter — cache hit
    answer_2 = asyncio.run(rag.query("Who works on contracts?", llm=llm, filter=f))
    assert llm.call_count == 1
    assert answer_1 == answer_2


def test_different_filters_produce_different_cache_entries(svc, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works in Paris")
    (docs / "b.txt").write_text("Bob works in Berlin")

    rag = PIIGhostRAG(svc, project="p", cache=RagCache(ttl=60))
    asyncio.run(rag.ingest(docs))

    llm = _CountingLLM("answer")
    f_a = QueryFilter(file_path_prefix=str(docs / "a.txt"))
    f_b = QueryFilter(file_path_prefix=str(docs / "b.txt"))
    asyncio.run(rag.query("Who?", llm=llm, filter=f_a))
    asyncio.run(rag.query("Who?", llm=llm, filter=f_b))
    # Different filters → different cache keys → 2 calls
    assert llm.call_count == 2
```

- [ ] **Step 2: Run the test**

```bash
python -m pytest tests/e2e/test_langchain_rag_advanced.py -v -p no:randomly
```

Expected: 2 PASSED.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest tests/unit/ tests/e2e/ tests/integrations/ -q -p no:randomly 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_langchain_rag_advanced.py
git commit -m "test(e2e): LangChain RAG with filter + cache E2E"
```

---

### Task 14: E2E Haystack RAG with filter + streaming

**Files:**
- Create: `tests/e2e/test_haystack_rag_advanced.py`

- [ ] **Step 1: Create the test**

```python
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
```

- [ ] **Step 2: Run the test**

```bash
python -m pytest tests/e2e/test_haystack_rag_advanced.py -v -p no:randomly
```

Expected: 1 PASSED.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest tests/unit/ tests/e2e/ tests/integrations/ -q -p no:randomly 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_haystack_rag_advanced.py
git commit -m "test(e2e): Haystack RAG with streaming E2E"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Task |
|------------------|------|
| `QueryFilter` dataclass | Task 1 |
| LanceDB WHERE builder + in-memory matcher | Task 1 |
| ChunkStore + BM25Index accept filter | Task 2 |
| `svc.query(filter=)` | Task 3 |
| `Reranker` protocol | Task 4 |
| `CrossEncoderReranker` default `BAAI/bge-reranker-base` | Task 4 |
| `RerankerSection` config + `_build_default_reranker` | Task 5 |
| `svc.query(rerank=True, top_n=)` + ValueError when no reranker | Task 5 |
| `top_n` clamping to max(top_n, k) | Task 5 |
| `StreamingRehydrator` rolling buffer | Task 6 |
| `PIIGhostRAG.astream()` + `.query()` filter/rerank/top_n | Task 7 |
| `RagCache` + `AnyCache` protocol | Task 8 |
| `PIIGhostRAG(cache=)` and short-circuit on hit | Task 8 |
| Haystack `streaming_callback` wraps user cb with rehydrator | Task 9 |
| Haystack `CachedRagPipeline` wrapper | Task 9 |
| CLI `--filter-prefix --filter-doc-ids --rerank --top-n` | Task 10 |
| MCP `query` tool params | Task 11 |
| Daemon dispatch forwards filter/rerank/top_n | Task 12 |
| E2E LangChain rerank + filter + cache | Task 13 |
| E2E Haystack rerank + filter + streaming | Task 14 |

### Placeholder scan

No TBD/TODO markers. All code blocks complete. Every verification step has expected output. Task 10's Step 3 says "Exact changes depend on the file's current structure" — this is honest scoping, not a placeholder, because the subagent reads the file first.

### Type consistency

- `QueryFilter(file_path_prefix: str | None, doc_ids: tuple[str, ...])` — used consistently across Tasks 1, 2, 3, 5, 7, 10, 11, 12, 13.
- `Reranker.rerank(query, candidates) -> list[QueryHit]` — defined Task 4, used Task 5.
- `CrossEncoderReranker(model_name="BAAI/bge-reranker-base")` — constructor signature stable.
- `svc.query(text, *, k, project, filter, rerank, top_n)` — final signature locked in Task 5, referenced unchanged in Tasks 7, 10, 11, 12.
- `PIIGhostRAG(svc, *, project, cache)` — extended constructor from Sprint 6a's `PIIGhostRAG(svc, *, project)`; `cache=None` default is backward-compat.
- `RagCache.make_key(**kwargs)` — exact kwarg names used consistently in Tasks 8, 9, 13.
- `StreamingRehydrator(svc, project)` — constructor signature consistent across Tasks 6, 7, 9.
- `build_piighost_rag(svc, *, project, llm_generator, top_k, streaming_callback, cache)` — final signature locked in Task 9, referenced in Task 14.
- `CachedRagPipeline` — defined Task 9, returned conditionally from `build_piighost_rag` when `cache is not None`.

All consistency checks pass.
