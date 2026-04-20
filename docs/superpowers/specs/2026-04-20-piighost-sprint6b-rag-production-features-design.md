# piighost Sprint 6b — RAG Production Features Design

**Date:** 2026-04-20
**Scope:** Add four production features on top of Sprint 6a's RAG wrappers: metadata filters, cross-encoder reranking, streaming answers, and answer caching. Layering: filters + reranking at the service layer (benefit CLI + MCP + wrappers); streaming + caching at the wrapper layer (LLM-specific).

---

## Goals

1. `QueryFilter` dataclass + LanceDB WHERE builder. `svc.query(filter=QueryFilter(...))` supports `file_path_prefix` and `doc_ids` filters.
2. `Reranker` protocol + `CrossEncoderReranker` (default `BAAI/bge-reranker-base`, multilingual). `svc.query(rerank=True, top_n=20)` retrieves top_n, reranks with cross-encoder, returns top k.
3. `StreamingRehydrator` with a rolling buffer that never yields partial `<LABEL:hash>` tokens. `PIIGhostRAG.astream(query, llm=...)` yields rehydrated chunks safely.
4. `RagCache` aiocache wrapper. `PIIGhostRAG(svc, cache=RagCache())` caches final answers keyed on anonymized-query hash. Default 300s TTL, `SimpleMemoryCache` backend.
5. CLI + MCP + daemon propagate `filter` and `rerank` params (streaming + caching stay wrapper-only).

## Non-goals

- Label filter (`find docs containing EMAIL_ADDRESS entities`). Defers to a future sprint — requires joining `chunks` with `doc_entities` which isn't in the current LanceDB query path.
- Alternative rerankers (Cohere API, FlashRank, BGE-large). We ship ONE default model; the protocol lets users swap in their own.
- Caching of retrieval results (only final answers are cached). Retrieval is already fast via LanceDB indexes; caching it duplicates LanceDB's own page cache.
- Persistent cache across process restarts out of the box. Users who want this configure a Redis backend and pass it to `RagCache(backend=...)`.
- Streaming answer caching — streaming and cache-hit yield different user experiences; we document the trade-off and keep them mutually exclusive for a given call.
- Sprint 6a's PII-zero-leak invariants are preserved but not re-proven by new E2E tests in this sprint. Sprint 6b tests focus on feature correctness; the rerank + filter paths automatically inherit Sprint 6a's zero-leak coverage because they don't touch the LLM boundary.

---

## 1. Architecture overview

```
src/piighost/
├── reranker/
│   ├── __init__.py                [NEW]
│   ├── base.py                    [NEW] Reranker protocol
│   └── cross_encoder.py           [NEW] CrossEncoderReranker
├── indexer/
│   ├── filters.py                 [NEW] QueryFilter + WHERE builder
│   └── retriever.py               [MODIFY] BM25 search accepts filter
├── service/
│   ├── core.py                    [MODIFY] svc.query(filter=, rerank=, top_n=)
│   ├── config.py                  [MODIFY] RerankerSection
│   └── models.py                  [MODIFY] QueryResult.rerank_scores (optional)
├── integrations/
│   ├── langchain/
│   │   ├── rag.py                 [MODIFY] .astream(), .query() accepts filter/rerank/cache
│   │   ├── streaming.py           [NEW] StreamingRehydrator
│   │   └── cache.py               [NEW] RagCache + AnyCache protocol
│   └── haystack/
│       ├── rag.py                 [MODIFY] build_piighost_rag accepts filter, rerank, streaming_callback, cache
│       └── streaming.py           [NEW] Streaming callback wrapper
├── cli/commands/
│   └── query.py                   [MODIFY] --filter-prefix, --rerank, --top-n
├── daemon/
│   └── server.py                  [MODIFY] forward filter/rerank/top_n to svc.query
└── mcp/
    └── server.py                  [MODIFY] query tool signature gains filter/rerank/top_n
```

Two features at the service layer, two at the wrapper layer. The service layer never touches an LLM — keeps it testable in isolation and reusable by CLI/MCP/wrappers.

## 2. Filters — `QueryFilter` dataclass

```python
# src/piighost/indexer/filters.py
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
        """In-memory filter for BM25 results (which aren't filtered by LanceDB)."""
        if self.file_path_prefix and not file_path.startswith(self.file_path_prefix):
            return False
        if self.doc_ids and doc_id not in self.doc_ids:
            return False
        return True
```

**`doc_ids` is a `tuple` (not `list`)** so `QueryFilter` stays hashable — lets us use it as a dict key in the cache.

**LanceDB application:** `ChunkStore.vector_search(query_vec, k, filter=where_clause)` passes the WHERE clause to LanceDB's `.where()` call.

**BM25 application:** `BM25Index.search(query, k)` returns all candidates; filter is applied in Python before top-k selection. BM25 index is in-memory so post-filter is cheap.

**Fusion:** `reciprocal_rank_fusion` runs after both retrievers have filtered; the union of filtered hits is fused normally.

## 3. Reranker — protocol + CrossEncoder default

### 3.1 Protocol

```python
# src/piighost/reranker/base.py
from __future__ import annotations

from typing import Protocol

from piighost.service.models import QueryHit


class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: list[QueryHit]
    ) -> list[QueryHit]:
        """Return candidates re-sorted by rerank score (highest first).

        MUST NOT mutate `candidates`. Returns a new list with rerank_score
        set on each hit.
        """
```

### 3.2 `CrossEncoderReranker`

```python
# src/piighost/reranker/cross_encoder.py
from __future__ import annotations

import asyncio

from piighost.service.models import QueryHit


class CrossEncoderReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        from sentence_transformers import CrossEncoder
        self._model = CrossEncoder(model_name)

    async def rerank(self, query: str, candidates: list[QueryHit]) -> list[QueryHit]:
        if not candidates:
            return []
        pairs = [(query, hit.chunk) for hit in candidates]
        scores = await asyncio.to_thread(self._model.predict, pairs)
        scored = [
            hit.model_copy(update={"score": float(score), "rank": i})
            for i, (hit, score) in enumerate(zip(candidates, scores))
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        for i, hit in enumerate(scored):
            hit.rank = i
        return scored
```

Default model `BAAI/bge-reranker-base`: multilingual, ~280 MB, supports French/German/English/Spanish. First load fetches from HF Hub; subsequent loads hit the local cache. Model name overridable via `ServiceConfig.reranker.cross_encoder_model` or direct construction.

### 3.3 Config

```python
# src/piighost/service/config.py
class RerankerSection(BaseModel):
    backend: Literal["none", "cross_encoder"] = "none"
    cross_encoder_model: str = "BAAI/bge-reranker-base"
    top_n: int = 20  # default candidate pool size before reranking


class ServiceConfig(BaseModel):
    # ... existing fields ...
    reranker: RerankerSection = Field(default_factory=RerankerSection)
```

`_build_default_reranker(config)` returns `None` for `backend="none"` and `CrossEncoderReranker(config.reranker.cross_encoder_model)` for `backend="cross_encoder"`.

### 3.4 Service integration

```python
# PIIGhostService holds an optional reranker
self._reranker: Reranker | None = await _build_default_reranker(config)

# _ProjectService.query gains the signature below
async def query(
    self,
    text: str,
    *,
    k: int = 5,
    filter: "QueryFilter | None" = None,
    rerank: bool = False,
    top_n: int = 20,
) -> QueryResult:
    if rerank and self._reranker is None:
        raise ValueError("rerank=True but no reranker configured; set ServiceConfig.reranker.backend")
    fetch_k = top_n if rerank else k
    hits = await self._retrieve(text, k=fetch_k, filter=filter)
    if rerank:
        hits = await self._reranker.rerank(text, hits)
        hits = hits[:k]
    return QueryResult(query=text, hits=hits, k=k)
```

The existing retrieval path (`_retrieve`) is the current hybrid BM25+vector+RRF code, refactored to accept `k` and `filter`. No behavior change when `rerank=False` and `filter=None`.

## 4. Streaming — `StreamingRehydrator`

### 4.1 The rolling buffer

```python
# src/piighost/integrations/langchain/streaming.py
import re

from piighost.service.core import PIIGhostService


_OPEN_TOKEN_RE = re.compile(r"<[A-Z_]*:?[0-9a-f]*$")


class StreamingRehydrator:
    """Buffered rehydrator safe for token-spanning LLM streams."""

    def __init__(self, svc: PIIGhostService, project: str) -> None:
        self._svc = svc
        self._project = project
        self._buffer = ""

    async def feed(self, chunk: str) -> str:
        """Append chunk, emit the prefix safe to rehydrate now."""
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
        """Flush remaining buffer after the stream ends."""
        if not self._buffer:
            return ""
        result = await self._svc.rehydrate(
            self._buffer, project=self._project, strict=False
        )
        self._buffer = ""
        return result.text
```

`_OPEN_TOKEN_RE` detects an incomplete token at the buffer tail. Any `<`-anchored alphanumeric-and-colon-and-hex prefix that hasn't closed with `>` stays buffered. Once the closing `>` arrives (or arbitrary non-token text follows), we cut at the safe position and rehydrate everything before it.

### 4.2 LangChain `astream`

```python
# PIIGhostRAG, added method
async def astream(
    self,
    text: str,
    *,
    llm: "BaseLanguageModel",
    k: int = 5,
    filter: "QueryFilter | None" = None,
    rerank: bool = False,
    top_n: int = 20,
    prompt: "Any | None" = None,
) -> "AsyncIterator[str]":
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

### 4.3 Haystack streaming

Haystack 2.x generators accept a `streaming_callback: Callable[[StreamingChunk], None]`. `build_piighost_rag` gains a `streaming_callback` param that wraps the user's callback:

```python
def build_piighost_rag(
    svc,
    *,
    project="default",
    llm_generator=None,
    top_k=5,
    streaming_callback: Callable | None = None,
) -> Pipeline:
    ...
    if streaming_callback is not None and llm_generator is not None:
        rehydrator = StreamingRehydrator(svc, project)
        loop = asyncio.get_event_loop()  # or asyncio.new_event_loop() in helper

        def _wrapped(chunk: StreamingChunk) -> None:
            emitted = loop.run_until_complete(rehydrator.feed(chunk.content))
            if emitted:
                streaming_callback(StreamingChunk(content=emitted))

        setattr(llm_generator, "streaming_callback", _wrapped)
    ...
```

Haystack's streaming path is less uniform than LangChain's (each generator uses the callback differently). The implementation sets the attribute when the generator supports it; generators without a `streaming_callback` attribute fall back to non-streaming mode.

### 4.4 Safety invariant

`StreamingRehydrator.feed` guarantees:
- The emitted string never contains a partial `<LABEL:hash` (verified by unit tests).
- Any `<LABEL:hash>` in the emitted string has been rehydrated to real PII (the whole point).
- If a token in the buffer is unknown to the vault, `rehydrate(..., strict=False)` leaves it intact; the token flows to the user unchanged — no silent drop.

## 5. Caching — `RagCache`

### 5.1 AnyCache protocol

```python
# src/piighost/integrations/langchain/cache.py
from typing import Protocol


class AnyCache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...
```

### 5.2 `RagCache`

```python
import hashlib
import json

from aiocache import SimpleMemoryCache


class RagCache:
    """aiocache-backed answer cache for PIIGhostRAG.

    Keys hash only anonymized data — no raw PII in cache keys.
    Values are the final rehydrated answer.
    """

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
        return await self._backend.get(key)

    async def set(self, key: str, value: str) -> None:
        await self._backend.set(key, value, ttl=self._ttl)
```

### 5.3 Helpers

```python
def _prompt_fingerprint(prompt) -> str:
    if prompt is None:
        return "default"
    # LangChain PromptTemplate has template attr
    text = getattr(prompt, "template", repr(prompt))
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _llm_id(llm) -> str:
    name = type(llm).__name__
    model = getattr(llm, "model_name", None) or getattr(llm, "model", "")
    return f"{name}:{model}" if model else name
```

### 5.4 LangChain integration

```python
class PIIGhostRAG:
    def __init__(
        self,
        svc: PIIGhostService,
        *,
        project: str = "default",
        cache: RagCache | None = None,
    ) -> None:
        self._svc = svc
        self._project = project
        self._cache = cache

    async def query(
        self,
        text: str,
        *,
        k: int = 5,
        llm: "BaseLanguageModel | None" = None,
        prompt: "Any | None" = None,
        filter: "QueryFilter | None" = None,
        rerank: bool = False,
        top_n: int = 20,
    ) -> str:
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

        # ... retrieval with filter/rerank/top_n ...
        # ... LLM invocation ...
        # ... rehydration ...

        if cache_key is not None:
            await self._cache.set(cache_key, rehydrated.text)
        return rehydrated.text
```

Cache is consulted only when an LLM is present — `query(llm=None)` returns rehydrated context without caching (not useful to cache since no expensive LLM call occurred).

### 5.5 Haystack integration

Haystack pipelines can't easily short-circuit — we take a simpler approach: caching lives OUTSIDE the pipeline. `build_piighost_rag(..., cache=RagCache())` returns a `CachedRagPipeline` wrapper object (not a raw `Pipeline`) exposing the same `.run(inputs)` API:

```python
class CachedRagPipeline:
    def __init__(self, pipeline: Pipeline, svc, project, cache: RagCache) -> None:
        self._pipeline = pipeline
        self._svc = svc
        self._project = project
        self._cache = cache

    async def run_async(self, inputs: dict) -> dict:
        query_text = inputs["query_anonymizer"]["text"]
        anon = await self._svc.anonymize(query_text, project=self._project)
        cache_key = RagCache.make_key(
            project=self._project,
            anonymized_query=anon.anonymized,
            k=self._pipeline_top_k,
            filter_repr="",
            prompt_hash="haystack_default",
            llm_id="haystack",
        )
        hit = await self._cache.get(cache_key)
        if hit is not None:
            return {"rehydrator": {"text": hit}}

        # Delegate to the underlying pipeline (which runs sync internally)
        result = self._pipeline.run(inputs)
        answer = result.get("rehydrator", {}).get("text", "")
        if answer:
            await self._cache.set(cache_key, answer)
        return result

    def run(self, inputs: dict) -> dict:
        from piighost.integrations.haystack._base import run_coroutine_sync
        return run_coroutine_sync(self.run_async(inputs))
```

When `cache=None`, `build_piighost_rag` returns a bare `Pipeline` as in Sprint 6a — zero overhead for users who don't want caching. When `cache=...`, it returns a `CachedRagPipeline` wrapper.

### 5.6 Safety

- Cache **keys** hash only anonymized query + project + structural metadata. No raw PII.
- Cache **values** are the final rehydrated answer — they contain real PII. This is a deliberate choice: caching anonymized answers would require re-rehydrating on every hit, which defeats part of the cache's value. Users in high-sensitivity contexts should disable caching (`cache=None`) or use Redis with encryption-at-rest.
- When `cache=None`, behavior is identical to Sprint 6a — no caching, no overhead.

## 6. CLI + MCP + daemon surface

### CLI `query.py`:
```python
--filter-prefix PATH      # File path prefix filter
--filter-doc-ids CSV      # Comma-separated doc IDs
--rerank / --no-rerank    # Enable reranking
--top-n N                 # Candidate pool size (default 20)
```

Filter flags build a `QueryFilter` object before the daemon/service call. CLI does not expose streaming or caching — it's a one-shot query tool.

### MCP `query` tool signature:

```python
async def query(
    text: str,
    k: int = 5,
    project: str = "default",
    filter_prefix: str = "",
    filter_doc_ids: list[str] | None = None,
    rerank: bool = False,
    top_n: int = 20,
) -> dict: ...
```

MCP builds the `QueryFilter` from the flat params. Tool description documents the filter fields.

### Daemon dispatch:

```python
if method == "query":
    from piighost.indexer.filters import QueryFilter
    filter_obj = None
    if params.get("filter_prefix") or params.get("filter_doc_ids"):
        filter_obj = QueryFilter(
            file_path_prefix=params.get("filter_prefix") or None,
            doc_ids=tuple(params.get("filter_doc_ids") or ()),
        )
    result = await svc.query(
        params["text"],
        k=params.get("k", 5),
        project=params.get("project", "default"),
        filter=filter_obj,
        rerank=params.get("rerank", False),
        top_n=params.get("top_n", 20),
    )
    return result.model_dump()
```

## 7. Error handling

| Case | Response |
|------|----------|
| `filter` with empty tuple + None prefix | Treated as no filter (`to_lance_where` returns `None`) |
| `rerank=True` but no reranker configured | `ValueError("rerank=True but no reranker configured; set ServiceConfig.reranker.backend")` |
| `top_n < k` | Silently clamped: `top_n = max(top_n, k)` |
| Reranker model download fails (no internet, HF Hub down) | `sentence_transformers` raises — bubbles up from `CrossEncoderReranker.__init__`. User sees a clear error at service startup |
| `StreamingRehydrator.feed` receives text with open `<` that never closes | Buffer grows unbounded until stream ends; `finalize` emits the raw buffer. Not a leak — any `<` without a valid hash is just text |
| `RagCache` backend fails | `get()` catches `Exception` and returns `None` (treat as miss); `set()` catches and logs. Cache failure never breaks the RAG pipeline |
| Streaming + caching both configured for the same call | Stream bypasses cache. Document in the API docstring |

## 8. PII safety invariants (preserved)

- Filters operate on `file_path` and `doc_id` (neither is PII under our model — file paths may contain user-chosen labels but we don't treat them as detectable PII).
- Reranker receives `(query, chunk)` pairs where **both are anonymized** — the anonymized query from `svc.anonymize` and the anonymized chunks from LanceDB. No raw PII in cross-encoder inputs.
- `StreamingRehydrator` never emits a partial `<LABEL:hash` prefix (rolling buffer guarantees whole-token semantics).
- `RagCache` keys are hashes of anonymized data only. Values contain rehydrated answers (real PII) — users who want cache-side PII safety disable caching or use encrypted-at-rest Redis.

## 9. Testing (summary; see plan for full list)

| Layer | Tests |
|-------|-------|
| Unit | `QueryFilter.to_lance_where`, `QueryFilter.matches`, `CrossEncoderReranker` with a fake cross-encoder, `StreamingRehydrator.feed` edge cases (partial token at boundary, multi-chunk tokens, unknown tokens), `RagCache.make_key` determinism |
| Service integration | `svc.query(filter=...)` reduces hits, `svc.query(rerank=True)` reorders by fake reranker score, `top_n < k` clamping |
| LangChain wrapper | `PIIGhostRAG.astream` yields no partial tokens, cache hits short-circuit LLM call, combined filter+rerank call |
| Haystack wrapper | `build_piighost_rag(streaming_callback=...)` wraps user callback with rehydration, cache component writes+reads correctly |
| CLI | `piighost query --filter-prefix ... --rerank` help text + flag propagation (smoke test) |
| MCP | `query` tool accepts new fields and forwards them (integration via `tools["query"].run({...})`) |
| E2E | `test_langchain_rag_advanced.py` — rerank + filter + cache roundtrip. `test_haystack_rag_advanced.py` — rerank + filter + streaming roundtrip |

## 10. Acceptance criteria

- `svc.query(filter=QueryFilter(file_path_prefix="/a"))` returns only hits where `hit.file_path.startswith("/a")`.
- `svc.query(rerank=True, top_n=10, k=3)` fetches 10 candidates from hybrid retrieval, reranks them, returns 3.
- `PIIGhostRAG.astream(q, llm=fake_streaming_llm)` yields rehydrated chunks; test asserts no yielded chunk contains `<` followed by truncated content.
- `RagCache` hit on identical (project, anonymized_query, k, filter, prompt, llm) returns the same answer without invoking the LLM.
- CLI `piighost query "text" --rerank --filter-prefix /contracts` works end-to-end against the daemon.
- Sprint 6a's 325 tests + Sprint 6b's ~30 new tests all pass.
- The PII-zero-leak E2E tests from Sprint 6a continue to pass (reranker + filter paths don't cross the LLM boundary).

## 11. Dependencies

- `sentence-transformers` (already in `[index]` extra) — `CrossEncoder` class
- `aiocache` (already in `[cache]` extra) — `SimpleMemoryCache`, config helpers
- No new top-level dependencies. Users who don't opt into rerank or cache see zero new imports.

## 12. Out of scope (future sprint candidates)

- Label filter (`QueryFilter(label="EMAIL_ADDRESS")`) — requires joining `chunks` with `doc_entities`.
- Alternative rerankers (Cohere, FlashRank, bge-large) — Protocol is in place; users can inject their own.
- Persistent cache (Redis-backed by default) — configuration path exists, but default stays in-memory.
- Semantic cache (approximate matching of similar queries) — different caching paradigm, warrants its own design.
- Post-hoc PII scan of LLM output to catch hallucinated PII — orthogonal feature; defer to Sprint 7.
- Benchmarks / retrieval quality evaluation harness — useful but out of scope here.
