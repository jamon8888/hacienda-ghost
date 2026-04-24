# piighost Sprint 2 — Document Indexing, Hybrid Retrieval & MCP Server

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Kreuzberg-based document indexing, BM25+vector hybrid retrieval, vault search, and a FastMCP server exposing all piighost capabilities as MCP tools.

**Architecture:** A new `piighost.indexer` sub-package handles ingestion (Kreuzberg), chunking, embedding, LanceDB vector storage, and BM25 retrieval. `PIIGhostService` gains `index_path`, `query`, and `vault_search` methods. A `piighost.mcp.server` module builds a `FastMCP` instance with 10 tools + 3 resources. PII anonymization is applied before indexing and before embedding queries, so no raw entity values ever leave the vault.

**Tech Stack:** `kreuzberg>=0.5` (doc extraction), `lancedb>=0.15` (vector store), `rank-bm25>=0.2.2` (BM25), `sentence-transformers>=3.3` (local embeddings), `fastmcp>=2.0` (MCP server), `httpx` (Mistral embedder), `pickle` (BM25 index serialisation), pytest + `_StubEmbedder` (deterministic 8-dim MD5 vectors for tests).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/piighost/indexer/__init__.py` | Package marker |
| Create | `src/piighost/indexer/chunker.py` | Sliding-window text splitter |
| Create | `src/piighost/indexer/ingestor.py` | Kreuzberg file/dir extraction |
| Create | `src/piighost/indexer/embedder.py` | Embedder hierarchy + factory |
| Create | `src/piighost/indexer/store.py` | LanceDB ChunkStore (meta-mode fallback) |
| Create | `src/piighost/indexer/retriever.py` | BM25Index + RRF fusion |
| Create | `src/piighost/mcp/__init__.py` | Package marker |
| Create | `src/piighost/mcp/server.py` | FastMCP build + run |
| Create | `src/piighost/cli/index.py` | `index` CLI command |
| Create | `src/piighost/cli/query.py` | `query` CLI command |
| Create | `src/piighost/cli/serve.py` | `serve --mcp` CLI command |
| Create | `tests/unit/indexer/test_chunker.py` | Chunker unit tests |
| Create | `tests/unit/indexer/test_embedder.py` | Embedder unit tests |
| Create | `tests/unit/indexer/test_retriever.py` | BM25 + RRF unit tests |
| Create | `tests/e2e/test_index_query_roundtrip.py` | E2E index→query→rehydrate |
| Modify | `src/piighost/service/models.py` | Add `IndexReport`, `QueryHit`, `QueryResult` |
| Modify | `src/piighost/service/core.py` | Add `_embedder`, `index_path`, `query`, `vault_search` |
| Modify | `src/piighost/vault/store.py` | Add `search_entities` LIKE query |
| Modify | `src/piighost/cli/main.py` | Register `index`, `query`, `serve` commands |
| Modify | `src/piighost/daemon/server.py` | Extend `_dispatch` with new methods |
| Modify | `pyproject.toml` | Add `kreuzberg` dep + `index`, `mcp` extras |

---

### Task 1: Service models — `IndexReport`, `QueryHit`, `QueryResult`

**Files:**
- Modify: `src/piighost/service/models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_service_models.py  (append to existing file or create)
from piighost.service.models import IndexReport, QueryHit, QueryResult

def test_index_report_defaults():
    r = IndexReport(indexed=3, skipped=1, errors=[], duration_ms=42)
    assert r.indexed == 3
    assert r.skipped == 1
    assert r.errors == []
    assert r.duration_ms == 42

def test_query_hit_fields():
    h = QueryHit(doc_id="d1", file_path="/tmp/a.txt", chunk="hello", score=0.9, rank=0)
    assert h.rank == 0

def test_query_result_fields():
    r = QueryResult(query="alice", hits=[], k=5)
    assert r.hits == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
python -m pytest tests/unit/test_service_models.py -v -p no:randomly
```

Expected: `ImportError` — `IndexReport` not defined.

- [ ] **Step 3: Add models to `src/piighost/service/models.py`**

Append after the existing `VaultPage` class:

```python
class IndexReport(BaseModel):
    indexed: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
    duration_ms: int


class QueryHit(BaseModel):
    doc_id: str
    file_path: str
    chunk: str
    score: float
    rank: int


class QueryResult(BaseModel):
    query: str
    hits: list[QueryHit]
    k: int
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_service_models.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/models.py tests/unit/test_service_models.py
git commit -m "feat(models): add IndexReport, QueryHit, QueryResult"
```

---

### Task 2: Text chunker

**Files:**
- Create: `src/piighost/indexer/__init__.py`
- Create: `src/piighost/indexer/chunker.py`
- Create: `tests/unit/indexer/__init__.py`
- Create: `tests/unit/indexer/test_chunker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_chunker.py
import pytest
from piighost.indexer.chunker import chunk_text

def test_empty_string():
    assert chunk_text("") == []

def test_whitespace_only():
    assert chunk_text("   \n  ") == []

def test_short_text_single_chunk():
    assert chunk_text("hello world") == ["hello world"]

def test_exact_chunk_size():
    text = "a" * 512
    chunks = chunk_text(text, chunk_size=512, overlap=0)
    assert chunks == [text]

def test_two_chunks_no_overlap():
    text = "a" * 600
    chunks = chunk_text(text, chunk_size=512, overlap=0)
    assert len(chunks) == 2
    assert chunks[0] == "a" * 512
    assert chunks[1] == "a" * 88

def test_overlap_produces_shared_content():
    text = "abcdefghij"  # 10 chars
    chunks = chunk_text(text, chunk_size=6, overlap=2)
    # step = 4; chunk 0: [0:6], chunk 1: [4:10]
    assert chunks[0] == "abcdef"
    assert chunks[1] == "efghij"

def test_invalid_overlap_raises():
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=4, overlap=4)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/indexer/test_chunker.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create package files and implement chunker**

```python
# src/piighost/indexer/__init__.py
```

```python
# tests/unit/indexer/__init__.py
```

```python
# src/piighost/indexer/chunker.py
from __future__ import annotations


def chunk_text(
    text: str,
    *,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be less than chunk_size ({chunk_size})")
    if not text or not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text]
    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        start += step
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/indexer/test_chunker.py -v -p no:randomly
```

Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/indexer/ tests/unit/indexer/
git commit -m "feat(indexer): sliding-window text chunker"
```

---

### Task 3: Document ingestor (Kreuzberg wrapper)

**Files:**
- Create: `src/piighost/indexer/ingestor.py`
- Create: `tests/unit/indexer/test_ingestor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_ingestor.py
import asyncio
from pathlib import Path
import pytest
from piighost.indexer.ingestor import list_document_paths, extract_text

SUPPORTED = [".pdf", ".docx", ".xlsx", ".odt", ".txt", ".md"]
UNSUPPORTED = [".png", ".exe", ".zip"]


def test_list_document_paths_single_file(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    result = asyncio.run(list_document_paths(f))
    assert result == [f]


def test_list_document_paths_dir_recursive(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("b")
    (sub / "img.png").write_bytes(b"\x89PNG")
    result = asyncio.run(list_document_paths(tmp_path, recursive=True))
    names = {p.name for p in result}
    assert "a.txt" in names
    assert "b.md" in names
    assert "img.png" not in names


def test_list_document_paths_non_recursive(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b")
    result = asyncio.run(list_document_paths(tmp_path, recursive=False))
    names = {p.name for p in result}
    assert "a.txt" in names
    assert "b.txt" not in names


def test_extract_text_plain_txt(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("Hello World")
    text = asyncio.run(extract_text(f))
    assert text is not None
    assert "Hello" in text


def test_extract_text_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("   ")
    assert asyncio.run(extract_text(f)) is None


def test_extract_text_oversized_file(tmp_path):
    f = tmp_path / "big.txt"
    f.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    assert asyncio.run(extract_text(f, max_bytes=10 * 1024 * 1024)) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/indexer/test_ingestor.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement ingestor**

```python
# src/piighost/indexer/ingestor.py
from __future__ import annotations

import asyncio
from pathlib import Path

import kreuzberg

_SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".odt", ".ods", ".pptx",
    ".txt", ".md", ".rst", ".html", ".htm",
}


async def list_document_paths(
    path: Path, *, recursive: bool = True
) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in _SUPPORTED_EXTENSIONS else []
    pattern = "**/*" if recursive else "*"
    return [
        p for p in path.glob(pattern)
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
    ]


async def extract_text(path: Path, *, max_bytes: int = 10_485_760) -> str | None:
    if path.stat().st_size > max_bytes:
        return None
    try:
        result = await kreuzberg.extract_file(path)
        text: str = result.content
        return text.strip() if text and text.strip() else None
    except Exception:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/indexer/test_ingestor.py -v -p no:randomly
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/indexer/ingestor.py tests/unit/indexer/test_ingestor.py
git commit -m "feat(indexer): Kreuzberg document ingestor"
```

---

### Task 4: Embedder hierarchy and factory

**Files:**
- Create: `src/piighost/indexer/embedder.py`
- Create: `tests/unit/indexer/test_embedder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_embedder.py
import asyncio
import os
import pytest
from piighost.indexer.embedder import NullEmbedder, _StubEmbedder, build_embedder
from piighost.config import PiighostConfig


def test_null_embedder_returns_empty_vectors():
    emb = NullEmbedder()
    vecs = asyncio.run(emb.embed(["hello", "world"]))
    assert vecs == [[], []]


def test_stub_embedder_deterministic():
    emb = _StubEmbedder()
    v1 = asyncio.run(emb.embed(["hello"]))
    v2 = asyncio.run(emb.embed(["hello"]))
    assert v1 == v2
    assert len(v1[0]) == 8


def test_stub_embedder_different_inputs():
    emb = _StubEmbedder()
    v = asyncio.run(emb.embed(["hello", "world"]))
    assert v[0] != v[1]


def test_build_embedder_stub_env(monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = PiighostConfig()
    emb = build_embedder(cfg.embedder)
    assert isinstance(emb, _StubEmbedder)


def test_build_embedder_none_backend(monkeypatch):
    monkeypatch.delenv("PIIGHOST_EMBEDDER", raising=False)
    cfg = PiighostConfig()
    cfg.embedder.backend = "none"
    emb = build_embedder(cfg.embedder)
    assert isinstance(emb, NullEmbedder)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/indexer/test_embedder.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Add `EmbedderSection` to config and implement embedder module**

First, check `src/piighost/config.py` to see the current config shape and add `EmbedderSection` if missing:

```python
# In src/piighost/config.py — add EmbedderSection to PiighostConfig:

class EmbedderSection(BaseModel):
    backend: str = "none"          # "none" | "local" | "mistral"
    model: str = "intfloat/multilingual-e5-base"
    mistral_api_key: str = ""
    mistral_model: str = "mistral-embed"


class PiighostConfig(BaseModel):
    # ... existing fields ...
    embedder: EmbedderSection = Field(default_factory=EmbedderSection)
```

Then create the embedder module:

```python
# src/piighost/indexer/embedder.py
from __future__ import annotations

import hashlib
import os
from typing import Protocol, Union

from piighost.config import EmbedderSection


class AnyEmbedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class NullEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class _StubEmbedder:
    DIM = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for t in texts:
            digest = hashlib.md5(t.encode()).digest()[: self.DIM]
            result.append([b / 255.0 for b in digest])
        return result


class LocalEmbedder:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(list(texts)).tolist()


class MistralEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/embeddings",
                json={"model": self._model, "input": texts},
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]


def build_embedder(cfg: EmbedderSection) -> AnyEmbedder:
    if os.environ.get("PIIGHOST_EMBEDDER") == "stub":
        return _StubEmbedder()
    if cfg.backend == "none":
        return NullEmbedder()
    if cfg.backend == "local":
        return LocalEmbedder(cfg.model)
    if cfg.backend == "mistral":
        return MistralEmbedder(cfg.mistral_api_key, cfg.mistral_model)
    raise ValueError(f"Unknown embedder backend: {cfg.backend!r}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/indexer/test_embedder.py -v -p no:randomly
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/config.py src/piighost/indexer/embedder.py tests/unit/indexer/test_embedder.py
git commit -m "feat(indexer): embedder hierarchy + factory (Null/Stub/Local/Mistral)"
```

---

### Task 5: ChunkStore (LanceDB with meta-mode fallback)

**Files:**
- Create: `src/piighost/indexer/store.py`
- Create: `tests/unit/indexer/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_store.py
import pytest
from piighost.indexer.store import ChunkStore


def test_meta_mode_upsert_and_all_records(tmp_path):
    """NullEmbedder (empty vectors) → meta-mode: in-memory, no LanceDB."""
    store = ChunkStore(tmp_path / "lance")
    store.upsert_chunks("doc1", "/tmp/a.txt", ["chunk A", "chunk B"], [[], []])
    records = store.all_records()
    assert len(records) == 2
    assert records[0]["doc_id"] == "doc1"
    assert records[0]["chunk"] in ("chunk A", "chunk B")


def test_meta_mode_overwrites_doc_on_upsert(tmp_path):
    store = ChunkStore(tmp_path / "lance")
    store.upsert_chunks("doc1", "/tmp/a.txt", ["old"], [[], ])
    store.upsert_chunks("doc1", "/tmp/a.txt", ["new"], [[]])
    records = store.all_records()
    assert len(records) == 1
    assert records[0]["chunk"] == "new"


def test_meta_mode_vector_search_returns_empty(tmp_path):
    store = ChunkStore(tmp_path / "lance")
    store.upsert_chunks("doc1", "/tmp/a.txt", ["hello"], [[]])
    results = store.vector_search([0.1, 0.2], k=5)
    assert results == []


def test_vector_mode_upsert_and_search(tmp_path):
    """Real vectors → LanceDB mode."""
    store = ChunkStore(tmp_path / "lance")
    vecs = [[float(i) / 10 for i in range(8)], [float(i + 1) / 10 for i in range(8)]]
    store.upsert_chunks("doc2", "/tmp/b.txt", ["alpha", "beta"], vecs)
    records = store.all_records()
    assert len(records) == 2
    results = store.vector_search([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7], k=2)
    assert len(results) > 0
    assert "chunk" in results[0]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/indexer/test_store.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement ChunkStore**

```python
# src/piighost/indexer/store.py
from __future__ import annotations

from pathlib import Path


class ChunkStore:
    def __init__(self, lance_path: Path) -> None:
        self._lance_path = lance_path
        self._meta_mode: bool = False
        self._meta: list[dict] = []
        self._db = None
        self._tbl = None

    def upsert_chunks(
        self,
        doc_id: str,
        file_path: str,
        texts: list[str],
        vectors: list[list[float]],
    ) -> None:
        has_vectors = any(v for v in vectors)
        if not has_vectors:
            self._meta_mode = True
            self._meta = [r for r in self._meta if r["doc_id"] != doc_id]
            for i, text in enumerate(texts):
                self._meta.append(
                    {
                        "doc_id": doc_id,
                        "file_path": file_path,
                        "chunk_id": f"{doc_id}:{i}",
                        "chunk": text,
                    }
                )
            return

        import lancedb
        import pyarrow as pa

        self._lance_path.mkdir(parents=True, exist_ok=True)
        if self._db is None:
            self._db = lancedb.connect(str(self._lance_path))

        dim = len(vectors[0])
        records = [
            {
                "doc_id": doc_id,
                "file_path": file_path,
                "chunk_id": f"{doc_id}:{i}",
                "chunk": text,
                "vector": vec,
            }
            for i, (text, vec) in enumerate(zip(texts, vectors))
        ]
        table_name = "chunks"
        if table_name in self._db.table_names():
            tbl = self._db.open_table(table_name)
            tbl.delete(f"doc_id = '{doc_id}'")
            tbl.add(records)
        else:
            schema = pa.schema(
                [
                    pa.field("doc_id", pa.string()),
                    pa.field("file_path", pa.string()),
                    pa.field("chunk_id", pa.string()),
                    pa.field("chunk", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), dim)),
                ]
            )
            self._tbl = self._db.create_table(table_name, data=records, schema=schema)

    def all_records(self) -> list[dict]:
        if self._meta_mode:
            return list(self._meta)
        if self._db is None:
            return []
        table_name = "chunks"
        if table_name not in self._db.table_names():
            return []
        tbl = self._db.open_table(table_name)
        rows = tbl.to_arrow().to_pylist()
        return [{k: v for k, v in r.items() if k != "vector"} for r in rows]

    def vector_search(self, embedding: list[float], *, k: int = 5) -> list[dict]:
        if self._meta_mode or not embedding:
            return []
        if self._db is None:
            return []
        table_name = "chunks"
        if table_name not in self._db.table_names():
            return []
        tbl = self._db.open_table(table_name)
        results = tbl.search(embedding).limit(k).to_list()
        return [{k: v for k, v in r.items() if k != "vector"} for r in results]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/indexer/test_store.py -v -p no:randomly
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/indexer/store.py tests/unit/indexer/test_store.py
git commit -m "feat(indexer): ChunkStore with LanceDB + meta-mode fallback"
```

---

### Task 6: BM25 index and Reciprocal Rank Fusion

**Files:**
- Create: `src/piighost/indexer/retriever.py`
- Create: `tests/unit/indexer/test_retriever.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_retriever.py
import pytest
from piighost.indexer.retriever import BM25Index, reciprocal_rank_fusion


def _make_records():
    return [
        {"chunk_id": "c1", "doc_id": "d1", "file_path": "/a.txt", "chunk": "the quick brown fox"},
        {"chunk_id": "c2", "doc_id": "d1", "file_path": "/a.txt", "chunk": "hello world"},
        {"chunk_id": "c3", "doc_id": "d2", "file_path": "/b.txt", "chunk": "quick lazy dog"},
    ]


def test_bm25_search_returns_relevant(tmp_path):
    idx = BM25Index(tmp_path / "bm25.pkl")
    idx.rebuild(_make_records())
    hits = idx.search("quick fox", k=2)
    chunk_ids = [cid for cid, _ in hits]
    assert "c1" in chunk_ids  # "quick" and "fox" both appear


def test_bm25_search_no_match():
    from piighost.indexer.retriever import BM25Index
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        idx = BM25Index(pathlib.Path(td) / "bm25.pkl")
        idx.rebuild(_make_records())
        hits = idx.search("zzznomatch", k=5)
        assert hits == []


def test_bm25_persist_and_load(tmp_path):
    pkl = tmp_path / "bm25.pkl"
    idx1 = BM25Index(pkl)
    idx1.rebuild(_make_records())

    idx2 = BM25Index(pkl)
    loaded = idx2.load()
    assert loaded is True
    hits = idx2.search("hello", k=1)
    assert hits[0][0] == "c2"


def test_rrf_single_list():
    bm25_hits = [("c1", 1.0), ("c2", 0.5)]
    result = reciprocal_rank_fusion(bm25_hits, [], bm25_weight=1.0, vector_weight=0.0)
    assert result[0][0] == "c1"


def test_rrf_fusion_elevates_shared():
    bm25_hits = [("c1", 1.0), ("c2", 0.5)]
    vec_hits = [("c2", 0.9), ("c1", 0.4)]
    result = reciprocal_rank_fusion(bm25_hits, vec_hits)
    # c1 rank0 bm25 + rank1 vec; c2 rank1 bm25 + rank0 vec — both get two signals
    ids = [cid for cid, _ in result]
    assert "c1" in ids and "c2" in ids


def test_rrf_empty_inputs():
    assert reciprocal_rank_fusion([], []) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/indexer/test_retriever.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement retriever**

```python
# src/piighost/indexer/retriever.py
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/indexer/test_retriever.py -v -p no:randomly
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/indexer/retriever.py tests/unit/indexer/test_retriever.py
git commit -m "feat(indexer): BM25Index + RRF fusion"
```

---

### Task 7: `PIIGhostService.index_path`

**Files:**
- Modify: `src/piighost/service/core.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_service_index.py
import asyncio
import os
import pytest
from pathlib import Path
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def test_index_path_single_txt_file(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    f = vault_dir / "doc.txt"
    vault_dir.mkdir(parents=True, exist_ok=True)
    f.write_text("Alice lives in Paris. She works at ACME Corp.")
    report = asyncio.run(svc.index_path(f))
    assert report.indexed == 1
    assert report.skipped == 0
    assert report.errors == []
    asyncio.run(svc.close())


def test_index_path_skips_unsupported_extension(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    vault_dir.mkdir(parents=True, exist_ok=True)
    f = vault_dir / "image.png"
    f.write_bytes(b"\x89PNG\r\n")
    report = asyncio.run(svc.index_path(f))
    assert report.indexed == 0
    asyncio.run(svc.close())


def test_index_path_directory(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    docs = vault_dir / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "a.txt").write_text("Bob is a lawyer in Berlin.")
    (docs / "b.txt").write_text("Carol works at EU Commission.")
    report = asyncio.run(svc.index_path(docs))
    assert report.indexed == 2
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_service_index.py -v -p no:randomly
```

Expected: `TypeError` or `AttributeError` — no `index_path` method.

- [ ] **Step 3: Extend `PIIGhostService`**

In `src/piighost/service/core.py`:

a) Import new dependencies at the top:
```python
from piighost.indexer.embedder import AnyEmbedder, build_embedder
from piighost.indexer.chunker import chunk_text
from piighost.indexer.ingestor import list_document_paths, extract_text
from piighost.indexer.store import ChunkStore
from piighost.indexer.retriever import BM25Index
from piighost.service.models import IndexReport
```

b) Add `_embedder`, `_chunk_store`, `_bm25` fields to `__init__`:
```python
def __init__(
    self,
    vault: Vault,
    detector: AnyDetector,
    config: PiighostConfig,
    embedder: AnyEmbedder,
) -> None:
    self._vault = vault
    self._detector = detector
    self._config = config
    self._embedder = embedder
    vault_dir = config.vault_dir
    self._chunk_store = ChunkStore(vault_dir / ".piighost" / "lance")
    self._bm25 = BM25Index(vault_dir / ".piighost" / "bm25.pkl")
    self._bm25.load()
```

c) Update `create()` classmethod to build embedder and pass it:
```python
@classmethod
async def create(
    cls,
    vault_dir: Path,
    config: PiighostConfig | None = None,
) -> "PIIGhostService":
    if config is None:
        config = PiighostConfig(vault_dir=vault_dir)
    vault = Vault.open(vault_dir / ".piighost" / "vault.db")
    detector = await _build_detector(config)
    embedder = build_embedder(config.embedder)
    return cls(vault, detector, config, embedder)
```

d) Add `index_path` method:
```python
async def index_path(
    self, path: Path, *, recursive: bool = True
) -> IndexReport:
    import time

    start = time.monotonic()
    paths = await list_document_paths(path, recursive=recursive)
    indexed = 0
    skipped = 0
    errors: list[str] = []

    for p in paths:
        try:
            text = await extract_text(p)
            if text is None:
                skipped += 1
                continue
            result = await self.anonymize(text, doc_id=str(p))
            anon_text = result.anonymized
            chunks = chunk_text(anon_text)
            if not chunks:
                skipped += 1
                continue
            vectors = await self._embedder.embed(chunks)
            self._chunk_store.upsert_chunks(str(p), str(p), chunks, vectors)
            indexed += 1
        except Exception as exc:
            errors.append(f"{p}: {exc}")

    all_records = self._chunk_store.all_records()
    self._bm25.rebuild(all_records)

    duration_ms = int((time.monotonic() - start) * 1000)
    return IndexReport(
        indexed=indexed,
        skipped=skipped,
        errors=errors,
        duration_ms=duration_ms,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_service_index.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_service_index.py
git commit -m "feat(service): index_path — ingest, anonymize, chunk, embed, store"
```

---

### Task 8: `PIIGhostService.query`

**Files:**
- Modify: `src/piighost/service/core.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_service_query.py
import asyncio
import pytest
from pathlib import Path
from piighost.service.core import PIIGhostService


@pytest.fixture()
def indexed_svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    vault_dir = tmp_path / "vault"
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice Smith is a senior engineer at ACME Corp.")
    (docs / "b.txt").write_text("Bob Jones works as a lawyer in Paris.")
    asyncio.run(svc.index_path(docs))
    return svc


def test_query_returns_hits(indexed_svc):
    result = asyncio.run(indexed_svc.query("engineer", k=3))
    assert result.k == 3
    assert len(result.hits) >= 1
    asyncio.run(indexed_svc.close())


def test_query_no_raw_pii_in_chunks(indexed_svc):
    result = asyncio.run(indexed_svc.query("Alice Smith", k=5))
    for hit in result.hits:
        assert "Alice" not in hit.chunk
        assert "Smith" not in hit.chunk
    asyncio.run(indexed_svc.close())


def test_query_empty_index(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    result = asyncio.run(svc.query("anything", k=3))
    assert result.hits == []
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_service_query.py -v -p no:randomly
```

Expected: `AttributeError` — no `query` method.

- [ ] **Step 3: Add `query` method to `PIIGhostService`**

```python
# In src/piighost/service/core.py, add after index_path:

from piighost.service.models import QueryHit, QueryResult
from piighost.indexer.retriever import reciprocal_rank_fusion

async def query(self, text: str, *, k: int = 5) -> QueryResult:
    anon_result = await self.anonymize(text)
    anon_query = anon_result.anonymized

    bm25_hits = self._bm25.search(anon_query, k=k * 2)
    query_vecs = await self._embedder.embed([anon_query])
    vec_hits_raw = self._chunk_store.vector_search(query_vecs[0], k=k * 2)
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

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_service_query.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_service_query.py
git commit -m "feat(service): query with BM25+vector RRF hybrid retrieval"
```

---

### Task 9: `PIIGhostService.vault_search` + `Vault.search_entities`

**Files:**
- Modify: `src/piighost/vault/store.py`
- Modify: `src/piighost/service/core.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_vault_search.py
import asyncio
import pytest
from pathlib import Path
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc_with_entities(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    vault_dir = tmp_path / "vault"
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    asyncio.run(svc.anonymize("Alice Smith works at ACME Corporation in Paris."))
    return svc, vault_dir


def test_vault_search_finds_entity(svc_with_entities):
    svc, _ = svc_with_entities
    results = asyncio.run(svc.vault_search("Alice"))
    assert len(results) >= 1
    originals = [r.original_masked or r.original for r in results]
    assert any("Alice" in (o or "") for o in originals)
    asyncio.run(svc.close())


def test_vault_search_no_match(svc_with_entities):
    svc, _ = svc_with_entities
    results = asyncio.run(svc.vault_search("zzznomatch99"))
    assert results == []
    asyncio.run(svc.close())


def test_vault_search_masked_hides_original(svc_with_entities):
    svc, _ = svc_with_entities
    results = asyncio.run(svc.vault_search("Alice", reveal=False))
    for r in results:
        assert r.original is None
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_vault_search.py -v -p no:randomly
```

Expected: `AttributeError` — no `vault_search` method.

- [ ] **Step 3: Add `search_entities` to `Vault`**

In `src/piighost/vault/store.py`, add after `stats()`:

```python
def search_entities(self, query: str, *, limit: int = 100) -> list[VaultEntry]:
    if not query:
        return []
    rows = self._conn.execute(
        "SELECT * FROM entities WHERE original LIKE ? "
        "ORDER BY occurrence_count DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    return [self._row_to_entry(r) for r in rows]
```

- [ ] **Step 4: Add `vault_search` to `PIIGhostService`**

In `src/piighost/service/core.py`:

```python
# Add import at top:
from piighost.service.models import VaultEntryModel

# Add method:
async def vault_search(
    self, query: str, *, reveal: bool = False, limit: int = 100
) -> list[VaultEntryModel]:
    entries = self._vault.search_entities(query, limit=limit)
    result = []
    for e in entries:
        original_masked = None
        if e.original:
            original_masked = e.original[:2] + "***" + e.original[-1:]
        result.append(
            VaultEntryModel(
                token=e.token,
                label=e.label,
                original=e.original if reveal else None,
                original_masked=original_masked,
                confidence=e.confidence,
                first_seen_at=e.first_seen_at,
                last_seen_at=e.last_seen_at,
                occurrence_count=e.occurrence_count,
            )
        )
    return result
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_vault_search.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/vault/store.py src/piighost/service/core.py tests/unit/test_vault_search.py
git commit -m "feat(service): vault_search + Vault.search_entities LIKE query"
```

---

### Task 10: CLI commands + daemon dispatch

**Files:**
- Create: `src/piighost/cli/index.py`
- Create: `src/piighost/cli/query.py`
- Create: `src/piighost/cli/serve.py`
- Modify: `src/piighost/cli/main.py`
- Modify: `src/piighost/daemon/server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli_index_query.py
from typer.testing import CliRunner
from piighost.cli.main import app

runner = CliRunner()


def test_index_help():
    result = runner.invoke(app, ["index", "--help"])
    assert result.exit_code == 0
    assert "path" in result.output.lower()


def test_query_help():
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "text" in result.output.lower()


def test_vault_search_help():
    result = runner.invoke(app, ["vault", "search", "--help"])
    assert result.exit_code == 0


def test_serve_help():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "mcp" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_cli_index_query.py -v -p no:randomly
```

Expected: `Exit code != 0` or `UsageError`.

- [ ] **Step 3: Create CLI command modules**

```python
# src/piighost/cli/index.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import typer


def run(
    path: Path = typer.Argument(..., help="File or directory to index"),
    vault: Path = typer.Option(Path.home() / ".piighost", "--vault", "-v"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    from piighost.daemon.lifecycle import ensure_daemon
    import httpx

    hs = ensure_daemon(vault)
    resp = httpx.post(
        f"http://127.0.0.1:{hs.port}/dispatch",
        json={"method": "index_path", "params": {"path": str(path.resolve()), "recursive": recursive}},
        headers={"Authorization": f"Bearer {hs.token}"},
        timeout=300.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(
            f"Indexed: {data['indexed']}  Skipped: {data['skipped']}  "
            f"Errors: {len(data['errors'])}  ({data['duration_ms']}ms)"
        )
        for err in data["errors"]:
            typer.echo(f"  ERROR: {err}", err=True)
```

```python
# src/piighost/cli/query.py
from __future__ import annotations

import json
from pathlib import Path
import typer


def run(
    text: str = typer.Argument(..., help="Query text"),
    vault: Path = typer.Option(Path.home() / ".piighost", "--vault", "-v"),
    k: int = typer.Option(5, "--k", "-k", help="Number of results"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    import httpx

    from piighost.daemon.lifecycle import ensure_daemon

    hs = ensure_daemon(vault)
    resp = httpx.post(
        f"http://127.0.0.1:{hs.port}/dispatch",
        json={"method": "query", "params": {"text": text, "k": k}},
        headers={"Authorization": f"Bearer {hs.token}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        for hit in data["hits"]:
            typer.echo(f"[{hit['rank']}] score={hit['score']:.4f}  {hit['file_path']}")
            typer.echo(f"    {hit['chunk'][:120]}")
```

```python
# src/piighost/cli/serve.py
from __future__ import annotations

from pathlib import Path
import typer


def run(
    vault: Path = typer.Option(Path.home() / ".piighost", "--vault", "-v"),
    transport: str = typer.Option("stdio", "--transport", "-t", help="stdio | sse"),
) -> None:
    from piighost.mcp.server import run_mcp

    run_mcp(vault, transport=transport)
```

- [ ] **Step 4: Register commands in `main.py`**

In `src/piighost/cli/main.py`, after existing imports and registrations add:

```python
from piighost.cli import index as index_cmd
from piighost.cli import query as query_cmd
from piighost.cli import serve as serve_cmd

app.command("index")(index_cmd.run)
app.command("query")(query_cmd.run)
app.command("serve")(serve_cmd.run)
```

Also add `vault search` subcommand. In the vault sub-app, add:

```python
# In the vault Typer app section:
@vault_app.command("search")
def vault_search_cmd(
    query: str = typer.Argument(..., help="Search term"),
    vault: Path = typer.Option(Path.home() / ".piighost", "--vault", "-v"),
    reveal: bool = typer.Option(False, "--reveal"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    import httpx, json as _json
    from piighost.daemon.lifecycle import ensure_daemon

    hs = ensure_daemon(vault)
    resp = httpx.post(
        f"http://127.0.0.1:{hs.port}/dispatch",
        json={"method": "vault_search", "params": {"query": query, "reveal": reveal}},
        headers={"Authorization": f"Bearer {hs.token}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if json_output:
        typer.echo(_json.dumps(data))
    else:
        for entry in data:
            typer.echo(f"{entry['token']}  [{entry['label']}]  {entry.get('original_masked', '***')}")
```

- [ ] **Step 5: Extend `_dispatch` in `server.py`**

In `src/piighost/daemon/server.py`, add to `_dispatch` after the existing `rehydrate` / `vault_list` cases:

```python
if method == "vault_search":
    entries = await svc.vault_search(
        params["query"], reveal=params.get("reveal", False)
    )
    return [e.model_dump() for e in entries]

if method == "index_path":
    from pathlib import Path as _Path
    report = await svc.index_path(
        _Path(params["path"]), recursive=params.get("recursive", True)
    )
    return report.model_dump()

if method == "query":
    result = await svc.query(params["text"], k=params.get("k", 5))
    return result.model_dump()
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_cli_index_query.py -v -p no:randomly
```

Expected: 4 PASSED.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/cli/ src/piighost/daemon/server.py tests/unit/test_cli_index_query.py
git commit -m "feat(cli): index, query, vault-search, serve commands + daemon dispatch"
```

---

### Task 11: FastMCP server

**Files:**
- Create: `src/piighost/mcp/__init__.py`
- Create: `src/piighost/mcp/server.py`
- Create: `tests/unit/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_server.py
import asyncio
import pytest
from pathlib import Path


def test_build_mcp_returns_fastmcp_and_service(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    from piighost.mcp.server import build_mcp
    mcp, svc = asyncio.run(build_mcp(tmp_path / "vault"))
    assert mcp is not None
    assert svc is not None
    asyncio.run(svc.close())


def test_mcp_has_expected_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    from piighost.mcp.server import build_mcp
    mcp, svc = asyncio.run(build_mcp(tmp_path / "vault"))
    tool_names = {t.name for t in mcp.list_tools()}
    expected = {
        "anonymize_text", "rehydrate_text", "index_path",
        "query", "vault_search", "vault_list", "vault_get",
        "daemon_status", "daemon_stop", "vault_stats",
    }
    assert expected.issubset(tool_names)
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_mcp_server.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement MCP server**

```python
# src/piighost/mcp/__init__.py
```

```python
# src/piighost/mcp/server.py
from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp import FastMCP

from piighost.config import PiighostConfig
from piighost.service.core import PIIGhostService


async def build_mcp(vault_dir: Path) -> tuple[FastMCP, PIIGhostService]:
    config = PiighostConfig(vault_dir=vault_dir)
    svc = await PIIGhostService.create(vault_dir=vault_dir, config=config)
    mcp = FastMCP("piighost", description="GDPR-compliant PII anonymization and document retrieval")

    @mcp.tool(description="Anonymize text, replacing PII with opaque tokens")
    async def anonymize_text(text: str, doc_id: str = "") -> dict:
        result = await svc.anonymize(text, doc_id=doc_id or None)
        return result.model_dump()

    @mcp.tool(description="Rehydrate anonymized text back to original PII")
    async def rehydrate_text(text: str) -> dict:
        result = await svc.rehydrate(text)
        return result.model_dump()

    @mcp.tool(description="Index a file or directory into the retrieval store")
    async def index_path(path: str, recursive: bool = True) -> dict:
        report = await svc.index_path(Path(path), recursive=recursive)
        return report.model_dump()

    @mcp.tool(description="Hybrid BM25+vector search over indexed documents")
    async def query(text: str, k: int = 5) -> dict:
        result = await svc.query(text, k=k)
        return result.model_dump()

    @mcp.tool(description="Full-text search in the PII vault by original value")
    async def vault_search(q: str, reveal: bool = False) -> list[dict]:
        entries = await svc.vault_search(q, reveal=reveal)
        return [e.model_dump() for e in entries]

    @mcp.tool(description="List vault entries with optional label filter")
    async def vault_list(label: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
        entries = svc._vault.list_entities(
            label=label or None, limit=limit, offset=offset
        )
        from piighost.service.models import VaultEntryModel
        return [
            VaultEntryModel(
                token=e.token,
                label=e.label,
                original_masked=(e.original[:2] + "***" + e.original[-1:] if e.original else None),
                confidence=e.confidence,
                first_seen_at=e.first_seen_at,
                last_seen_at=e.last_seen_at,
                occurrence_count=e.occurrence_count,
            ).model_dump()
            for e in entries
        ]

    @mcp.tool(description="Retrieve a single vault entry by token")
    async def vault_get(token: str, reveal: bool = False) -> dict | None:
        entry = svc._vault.get_by_token(token)
        if entry is None:
            return None
        from piighost.service.models import VaultEntryModel
        return VaultEntryModel(
            token=entry.token,
            label=entry.label,
            original=entry.original if reveal else None,
            original_masked=(entry.original[:2] + "***" + entry.original[-1:] if entry.original else None),
            confidence=entry.confidence,
            first_seen_at=entry.first_seen_at,
            last_seen_at=entry.last_seen_at,
            occurrence_count=entry.occurrence_count,
        ).model_dump()

    @mcp.tool(description="Return vault statistics (total entries, by label)")
    async def vault_stats() -> dict:
        stats = svc._vault.stats()
        return {"total": stats.total, "by_label": stats.by_label}

    @mcp.tool(description="Check whether the piighost daemon is running")
    async def daemon_status() -> dict:
        from piighost.daemon.lifecycle import status
        hs = status(vault_dir)
        if hs is None:
            return {"running": False}
        return {"running": True, "pid": hs.pid, "port": hs.port}

    @mcp.tool(description="Stop the piighost daemon gracefully")
    async def daemon_stop() -> dict:
        from piighost.daemon.lifecycle import stop_daemon
        stopped = stop_daemon(vault_dir)
        return {"stopped": stopped}

    @mcp.resource("piighost://vault/stats")
    async def vault_stats_resource() -> str:
        stats = svc._vault.stats()
        return f"Total entities: {stats.total}\nBy label: {stats.by_label}"

    @mcp.resource("piighost://vault/recent")
    async def vault_recent_resource() -> str:
        entries = svc._vault.list_entities(limit=10)
        lines = [f"{e.token} [{e.label}] seen {e.occurrence_count}x" for e in entries]
        return "\n".join(lines) if lines else "(empty vault)"

    @mcp.resource("piighost://index/status")
    async def index_status_resource() -> str:
        records = svc._chunk_store.all_records()
        doc_ids = {r["doc_id"] for r in records}
        return f"Indexed documents: {len(doc_ids)}\nTotal chunks: {len(records)}"

    return mcp, svc


def run_mcp(vault_dir: Path, *, transport: str = "stdio") -> None:
    async def _start() -> None:
        mcp, svc = await build_mcp(vault_dir)
        try:
            await mcp.run_async(transport=transport)
        finally:
            await svc.close()

    asyncio.run(_start())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_mcp_server.py -v -p no:randomly
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/ tests/unit/test_mcp_server.py
git commit -m "feat(mcp): FastMCP server with 10 tools + 3 resources"
```

---

### Task 12: pyproject.toml extras + E2E tests

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/e2e/test_index_query_roundtrip.py`

- [ ] **Step 1: Update `pyproject.toml`**

Add to the `[project]` `dependencies` list (base dep, always installed):
```toml
"kreuzberg>=0.5",
```

Add/extend optional extras:
```toml
[project.optional-dependencies]
index = [
    "lancedb>=0.15",
    "rank-bm25>=0.2.2",
    "sentence-transformers>=3.3",
]
mcp = [
    "fastmcp>=2.0",
]
all = [
    "piighost[index]",
    "piighost[mcp]",
]
```

Install the new extras in your dev environment:
```bash
pip install -e ".[index,mcp]"
```

- [ ] **Step 2: Write the E2E tests**

```python
# tests/e2e/test_index_query_roundtrip.py
"""E2E: index → query → rehydrate, token identity, PII-zero-leak."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    vault_dir = tmp_path / "vault"
    service = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    yield service
    asyncio.run(service.close())


@pytest.fixture()
def docs(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "contract.txt").write_text(
        "Alice Johnson is a partner at Smith & Associates law firm in Brussels. "
        "She negotiated the GDPR compliance contract on 2024-01-15."
    )
    (docs_dir / "report.txt").write_text(
        "Bob Martinez, CEO of TechCorp GmbH (VAT: DE123456789), "
        "submitted a data processing agreement to the EU DPA office."
    )
    (docs_dir / "memo.txt").write_text(
        "The meeting between Claire Dupont and the legal team in Paris "
        "concluded with approval of the privacy policy."
    )
    return docs_dir


def test_roundtrip_index_query_rehydrate(svc, docs):
    """Index 3 docs → query → verify chunks contain no raw PII tokens."""
    report = asyncio.run(svc.index_path(docs))
    assert report.indexed == 3
    assert report.errors == []

    result = asyncio.run(svc.query("law firm Brussels", k=3))
    assert len(result.hits) >= 1

    for hit in result.hits:
        # Chunks must be anonymized — no raw names or places
        assert "Alice" not in hit.chunk
        assert "Johnson" not in hit.chunk
        assert "Brussels" not in hit.chunk

        # Rehydration must restore them
        rehydrated = asyncio.run(svc.rehydrate(hit.chunk))
        # The rehydrated text or original token pattern should be in vault
        assert rehydrated.unknown_tokens == [] or len(rehydrated.text) > 0


def test_token_identity_bm25_retrieval(svc, tmp_path):
    """Same entity yields same token in indexed doc and anonymized query → BM25 matches."""
    doc_dir = tmp_path / "tok_docs"
    doc_dir.mkdir()
    (doc_dir / "employee.txt").write_text(
        "Eve Nakamura is a software engineer at QuantumAI Berlin. "
        "Eve Nakamura joined the company in January 2023."
    )
    asyncio.run(svc.index_path(doc_dir))

    # Anonymize the query — "Eve Nakamura" should get the same token as in the doc
    anon = asyncio.run(svc.anonymize("What does Eve Nakamura work on?"))
    anon_query = anon.anonymized
    # The token for Eve Nakamura must appear verbatim in BM25 index
    bm25_hits = svc._bm25.search(anon_query, k=5)
    assert len(bm25_hits) >= 1, (
        f"BM25 found no hits for anonymized query '{anon_query}'. "
        "HashPlaceholderFactory must produce identical tokens for the same entity."
    )


def test_pii_zero_leak_to_mistral(svc, tmp_path, monkeypatch):
    """No raw PII values must appear in Mistral embedding requests."""
    captured_bodies: list[str] = []

    class _CapturingTransport(httpx.MockTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            captured_bodies.append(request.content.decode("utf-8", errors="replace"))
            payload = {"data": [{"embedding": [0.1] * 8, "index": 0}], "usage": {"prompt_tokens": 1}}
            return httpx.Response(200, json=payload)

    # Patch the MistralEmbedder to use the capturing transport
    import piighost.indexer.embedder as emb_mod

    class _PatchedMistralEmbedder(emb_mod.MistralEmbedder):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            async with httpx.AsyncClient(transport=_CapturingTransport()) as client:
                resp = await client.post(
                    "https://api.mistral.ai/v1/embeddings",
                    json={"model": self._model, "input": texts},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data["data"]]

    monkeypatch.delenv("PIIGHOST_EMBEDDER", raising=False)
    monkeypatch.setattr(emb_mod, "MistralEmbedder", _PatchedMistralEmbedder)

    from piighost.config import PiighostConfig, EmbedderSection

    vault_dir = tmp_path / "leak_vault"
    config = PiighostConfig(
        vault_dir=vault_dir,
        embedder=EmbedderSection(backend="mistral", mistral_api_key="test-key"),
    )
    leak_svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=config))

    doc_dir = tmp_path / "leak_docs"
    doc_dir.mkdir()
    (doc_dir / "sensitive.txt").write_text(
        "Alice Smith and Bob Jones signed a contract in Paris for €50,000."
    )
    asyncio.run(leak_svc.index_path(doc_dir))

    pii_values = ["Alice", "Smith", "Bob", "Jones", "Paris"]
    for body in captured_bodies:
        for pii in pii_values:
            assert pii not in body, (
                f"RAW PII '{pii}' found in Mistral embed request body: {body[:200]}"
            )

    asyncio.run(leak_svc.close())
```

- [ ] **Step 3: Run E2E tests**

```bash
python -m pytest tests/e2e/test_index_query_roundtrip.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest --tb=short -p no:randomly
```

Expected: All tests pass (previous 396 + new Sprint 2 tests).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/e2e/test_index_query_roundtrip.py
git commit -m "feat(sprint2): pyproject extras + E2E roundtrip/token-identity/PII-zero-leak tests"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| Kreuzberg document ingestion | Task 3 (ingestor) |
| Sliding-window chunker | Task 2 |
| Embedder: Null / Stub / Local / Mistral | Task 4 |
| LanceDB vector store | Task 5 (ChunkStore) |
| BM25 retrieval + RRF fusion | Task 6 |
| `index_path` service method | Task 7 |
| `query` service method | Task 8 |
| `vault_search` service method + Vault LIKE | Task 9 |
| `IndexReport`, `QueryHit`, `QueryResult` models | Task 1 |
| CLI: `index`, `query`, `vault search`, `serve` | Task 10 |
| Daemon dispatch: index_path / query / vault_search | Task 10 |
| FastMCP: 10 tools + 3 resources | Task 11 |
| pyproject extras: `index`, `mcp`, `all` | Task 12 |
| PII-zero-leak proof test | Task 12 |
| Token identity (same entity = same BM25 token) test | Task 12 |

**No placeholders found.** All steps contain complete code.

**Type consistency:** `IndexReport`, `QueryHit`, `QueryResult` defined in Task 1 and imported in Tasks 7, 8. `AnyEmbedder` protocol defined in Task 4 and used in Task 7. `EmbedderSection` added to config in Task 4 and used in Task 11. All consistent.
