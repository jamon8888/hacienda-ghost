# piighost Sprint 3 — Incremental Indexing & Doc Management

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `index_path` skip unchanged files (mtime + content-hash check), give every indexed file a stable content-addressed doc_id, and add `piighost rm` / `piighost index-status` for doc management.

**Architecture:** A new `indexed_files` SQLite table (schema v2) tracks each indexed file's content hash, mtime, and chunk count. `index_path` checks mtime before re-hashing; if unchanged it increments `unchanged` and moves on. A new `content_hash` utility (`indexer/identity.py`) produces the stable 16-char SHA-256 hex doc_id that replaces the current full-path string. `ChunkStore` gains `delete_doc` so stale chunks are removed before re-indexing. `PIIGhostService` gains `remove_doc` and `index_status` service methods, wired to new CLI commands and daemon dispatch.

**Tech Stack:** SQLite (schema migration), hashlib (SHA-256), existing `ChunkStore`/`BM25Index`/`Vault` APIs, Typer CLI, FastAPI daemon, pytest + `_StubDetector`/`_StubEmbedder`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/piighost/vault/schema.py` | Add `indexed_files` table + schema v2 migration |
| Modify | `src/piighost/vault/store.py` | `IndexedFileRecord` dataclass + CRUD + `delete_doc_entities` + aggregate counts |
| Create | `src/piighost/indexer/identity.py` | `content_hash(path) -> str` (16-char SHA-256 hex) |
| Modify | `src/piighost/service/models.py` | `IndexReport.unchanged`, `IndexedFileEntry`, `IndexStatus` |
| Modify | `src/piighost/indexer/store.py` | `ChunkStore.delete_doc(doc_id)` |
| Modify | `src/piighost/indexer/retriever.py` | `BM25Index.clear()` |
| Modify | `src/piighost/service/core.py` | Incremental skip in `index_path`; new `remove_doc`, `index_status` methods |
| Create | `src/piighost/cli/commands/rm.py` | `piighost rm <path>` (daemon-first) |
| Create | `src/piighost/cli/commands/index_status.py` | `piighost index-status` (daemon-first) |
| Modify | `src/piighost/cli/commands/index.py` | Add `--force/--no-force` option |
| Modify | `src/piighost/cli/main.py` | Register `rm`, `index-status` |
| Modify | `src/piighost/daemon/server.py` | Dispatch `remove_doc`, `index_status` |
| Create | `tests/unit/test_vault_indexed_files.py` | Vault CRUD for `indexed_files` |
| Create | `tests/unit/indexer/test_identity.py` | `content_hash` unit tests |
| Create | `tests/unit/test_service_incremental.py` | Incremental skip + stable doc_id |
| Create | `tests/unit/test_service_remove_doc.py` | `remove_doc` unit tests |
| Create | `tests/unit/test_service_index_status.py` | `index_status` unit tests |
| Create | `tests/unit/test_cli_rm_status.py` | `--help` smoke tests |
| Create | `tests/e2e/test_incremental_indexing.py` | E2E incremental behavior |

---

### Task 1: Schema v2 migration + `indexed_files` vault CRUD

**Files:**
- Modify: `src/piighost/vault/schema.py`
- Modify: `src/piighost/vault/store.py`
- Create: `tests/unit/test_vault_indexed_files.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_vault_indexed_files.py
import time
from piighost.vault.store import Vault


def _open(tmp_path):
    return Vault.open(tmp_path / "vault.db")


def test_upsert_and_get_by_path(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("abc123", "/docs/a.txt", "abc123", 1000.0, 5)
    rec = v.get_indexed_file_by_path("/docs/a.txt")
    assert rec is not None
    assert rec.doc_id == "abc123"
    assert rec.chunk_count == 5
    v.close()


def test_upsert_updates_existing(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("abc123", "/docs/a.txt", "abc123", 1000.0, 5)
    v.upsert_indexed_file("def456", "/docs/a.txt", "def456", 2000.0, 8)
    # path now points to new doc_id
    rec = v.get_indexed_file_by_path("/docs/a.txt")
    assert rec.doc_id == "def456"
    assert rec.chunk_count == 8
    v.close()


def test_delete_indexed_file(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("abc123", "/docs/a.txt", "abc123", 1000.0, 5)
    removed = v.delete_indexed_file("abc123")
    assert removed is True
    assert v.get_indexed_file_by_path("/docs/a.txt") is None
    v.close()


def test_list_indexed_files(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("aaa", "/a.txt", "aaa", 1.0, 2)
    v.upsert_indexed_file("bbb", "/b.txt", "bbb", 2.0, 3)
    files = v.list_indexed_files()
    assert len(files) == 2
    v.close()


def test_count_and_total_chunks(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("aaa", "/a.txt", "aaa", 1.0, 4)
    v.upsert_indexed_file("bbb", "/b.txt", "bbb", 2.0, 6)
    assert v.count_indexed_files() == 2
    assert v.total_chunk_count() == 10
    v.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
python -m pytest tests/unit/test_vault_indexed_files.py -v -p no:randomly
```

Expected: `AttributeError: 'Vault' object has no attribute 'upsert_indexed_file'`

- [ ] **Step 3: Add `indexed_files` table to schema**

In `src/piighost/vault/schema.py`, replace the entire file with:

```python
"""Vault DDL and forward-only migrations."""

from __future__ import annotations

import sqlite3

CURRENT_SCHEMA_VERSION = 2

_DDL = """
CREATE TABLE IF NOT EXISTS entities (
    token TEXT PRIMARY KEY,
    original TEXT NOT NULL,
    label TEXT NOT NULL,
    confidence REAL,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS doc_entities (
    doc_id TEXT NOT NULL,
    token TEXT NOT NULL REFERENCES entities(token),
    start_pos INTEGER,
    end_pos INTEGER,
    PRIMARY KEY (doc_id, token, start_pos)
);

CREATE TABLE IF NOT EXISTS indexed_files (
    doc_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    indexed_at INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schema_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_label ON entities(label);
CREATE INDEX IF NOT EXISTS idx_doc_entities_doc ON doc_entities(doc_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_indexed_files_path ON indexed_files(file_path);
"""

_MIGRATION_V1_TO_V2 = """
CREATE TABLE IF NOT EXISTS indexed_files (
    doc_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    indexed_at INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_indexed_files_path ON indexed_files(file_path);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotently create schema, run forward migrations, and stamp version."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_DDL)
    cur = conn.execute("SELECT COUNT(*) FROM schema_meta")
    if cur.fetchone()[0] == 0:
        import time
        conn.execute(
            "INSERT INTO schema_meta (singleton, version, created_at) VALUES (1, ?, ?)",
            (CURRENT_SCHEMA_VERSION, int(time.time())),
        )
        conn.commit()
        return
    # Forward migrations for existing databases
    row = conn.execute("SELECT version FROM schema_meta WHERE singleton = 1").fetchone()
    if row and row[0] < 2:
        conn.executescript(_MIGRATION_V1_TO_V2)
        conn.execute("UPDATE schema_meta SET version = 2 WHERE singleton = 1")
        conn.commit()
```

- [ ] **Step 4: Add `IndexedFileRecord` and CRUD methods to `src/piighost/vault/store.py`**

Add after the existing `VaultStats` dataclass and before the `Vault` class:

```python
@dataclass(frozen=True)
class IndexedFileRecord:
    doc_id: str
    file_path: str
    content_hash: str
    mtime: float
    indexed_at: int
    chunk_count: int
```

Add these methods inside the `Vault` class, after `search_entities`:

```python
# ---- indexed_files ----

def upsert_indexed_file(
    self,
    doc_id: str,
    file_path: str,
    content_hash: str,
    mtime: float,
    chunk_count: int,
) -> None:
    now = int(time.time())
    self._conn.execute(
        """
        INSERT INTO indexed_files
            (doc_id, file_path, content_hash, mtime, indexed_at, chunk_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(doc_id) DO UPDATE SET
            file_path      = excluded.file_path,
            content_hash   = excluded.content_hash,
            mtime          = excluded.mtime,
            indexed_at     = excluded.indexed_at,
            chunk_count    = excluded.chunk_count
        """,
        (doc_id, file_path, content_hash, mtime, now, chunk_count),
    )

def get_indexed_file_by_path(self, file_path: str) -> IndexedFileRecord | None:
    row = self._conn.execute(
        "SELECT * FROM indexed_files WHERE file_path = ?", (file_path,)
    ).fetchone()
    return self._row_to_indexed_file(row) if row else None

def get_indexed_file(self, doc_id: str) -> IndexedFileRecord | None:
    row = self._conn.execute(
        "SELECT * FROM indexed_files WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    return self._row_to_indexed_file(row) if row else None

def delete_indexed_file(self, doc_id: str) -> bool:
    cur = self._conn.execute(
        "DELETE FROM indexed_files WHERE doc_id = ?", (doc_id,)
    )
    return cur.rowcount > 0

def list_indexed_files(
    self, *, limit: int = 100, offset: int = 0
) -> list[IndexedFileRecord]:
    rows = self._conn.execute(
        "SELECT * FROM indexed_files ORDER BY indexed_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [self._row_to_indexed_file(r) for r in rows]

def count_indexed_files(self) -> int:
    (count,) = self._conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()
    return count

def total_chunk_count(self) -> int:
    (total,) = self._conn.execute(
        "SELECT COALESCE(SUM(chunk_count), 0) FROM indexed_files"
    ).fetchone()
    return total

def delete_doc_entities(self, doc_id: str) -> int:
    cur = self._conn.execute(
        "DELETE FROM doc_entities WHERE doc_id = ?", (doc_id,)
    )
    return cur.rowcount

@staticmethod
def _row_to_indexed_file(row: sqlite3.Row) -> IndexedFileRecord:
    return IndexedFileRecord(
        doc_id=row["doc_id"],
        file_path=row["file_path"],
        content_hash=row["content_hash"],
        mtime=row["mtime"],
        indexed_at=row["indexed_at"],
        chunk_count=row["chunk_count"],
    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_vault_indexed_files.py -v -p no:randomly
```

Expected: 5 PASSED.

- [ ] **Step 6: Verify existing tests still pass**

```bash
python -m pytest tests/unit/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing (schema migration is backward-compatible).

- [ ] **Step 7: Commit**

```bash
git add src/piighost/vault/schema.py src/piighost/vault/store.py tests/unit/test_vault_indexed_files.py
git commit -m "feat(vault): schema v2 — indexed_files table + CRUD methods"
```

---

### Task 2: Content hash utility

**Files:**
- Create: `src/piighost/indexer/identity.py`
- Create: `tests/unit/indexer/test_identity.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_identity.py
from piighost.indexer.identity import content_hash


def test_hash_is_16_chars(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello world")
    assert len(content_hash(f)) == 16


def test_hash_is_consistent(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello world")
    assert content_hash(f) == content_hash(f)


def test_hash_differs_for_different_content(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("hello")
    b.write_text("world")
    assert content_hash(a) != content_hash(b)


def test_hash_same_content_different_path(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "sub" / "b.txt"
    b.parent.mkdir()
    a.write_text("identical content")
    b.write_text("identical content")
    assert content_hash(a) == content_hash(b)


def test_hash_is_hex_string(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"\x00\x01\x02\xff")
    h = content_hash(f)
    int(h, 16)  # raises ValueError if not valid hex
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/indexer/test_identity.py -v -p no:randomly
```

Expected: `ModuleNotFoundError: No module named 'piighost.indexer.identity'`

- [ ] **Step 3: Implement the utility**

```python
# src/piighost/indexer/identity.py
from __future__ import annotations

import hashlib
from pathlib import Path


def content_hash(path: Path) -> str:
    """16-character hex SHA-256 digest of file content.

    Used as a stable, content-addressed doc_id. Two files with identical
    bytes produce the same hash regardless of path or mtime.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/indexer/test_identity.py -v -p no:randomly
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/indexer/identity.py tests/unit/indexer/test_identity.py
git commit -m "feat(indexer): content_hash — stable SHA-256 doc_id utility"
```

---

### Task 3: Incremental skip in `index_path` + stable doc_id

**Files:**
- Modify: `src/piighost/service/models.py` (add `unchanged` to `IndexReport`)
- Modify: `src/piighost/indexer/store.py` (add `ChunkStore.delete_doc`)
- Modify: `src/piighost/indexer/retriever.py` (add `BM25Index.clear`)
- Modify: `src/piighost/service/core.py` (`index_path` overhaul)
- Create: `tests/unit/test_service_incremental.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_service_incremental.py
import asyncio
from pathlib import Path
import pytest
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _make_svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir))


def test_index_report_has_unchanged_field(vault_dir, monkeypatch, tmp_path):
    svc = _make_svc(vault_dir, monkeypatch)
    f = tmp_path / "doc.txt"
    f.write_text("Alice works in Paris")
    report = asyncio.run(svc.index_path(f))
    assert hasattr(report, "unchanged")
    assert report.unchanged == 0
    asyncio.run(svc.close())


def test_second_index_unchanged(vault_dir, monkeypatch, tmp_path):
    svc = _make_svc(vault_dir, monkeypatch)
    f = tmp_path / "doc.txt"
    f.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(f))
    report2 = asyncio.run(svc.index_path(f))
    assert report2.indexed == 0
    assert report2.unchanged == 1
    asyncio.run(svc.close())


def test_force_reindexes_unchanged(vault_dir, monkeypatch, tmp_path):
    svc = _make_svc(vault_dir, monkeypatch)
    f = tmp_path / "doc.txt"
    f.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(f))
    report2 = asyncio.run(svc.index_path(f, force=True))
    assert report2.indexed == 1
    assert report2.unchanged == 0
    asyncio.run(svc.close())


def test_doc_id_is_content_hash(vault_dir, monkeypatch, tmp_path):
    """doc_id stored in indexed_files must equal content_hash(path)."""
    from piighost.indexer.identity import content_hash
    svc = _make_svc(vault_dir, monkeypatch)
    f = tmp_path / "doc.txt"
    f.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(f))
    rec = svc._vault.get_indexed_file_by_path(str(f))
    assert rec is not None
    assert rec.doc_id == content_hash(f)
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/test_service_incremental.py -v -p no:randomly
```

Expected: `AttributeError` on `unchanged` or `force`.

- [ ] **Step 3: Add `unchanged` to `IndexReport` in `src/piighost/service/models.py`**

Find the `IndexReport` class and replace it:

```python
class IndexReport(BaseModel):
    indexed: int
    skipped: int
    unchanged: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_ms: int
```

- [ ] **Step 4: Add `ChunkStore.delete_doc` to `src/piighost/indexer/store.py`**

Add this method inside the `ChunkStore` class, after `all_records`:

```python
def delete_doc(self, doc_id: str) -> None:
    if self._meta_mode:
        self._meta = [r for r in self._meta if r["doc_id"] != doc_id]
        return
    if self._db is None:
        return
    table_name = "chunks"
    if table_name not in self._db.list_tables().tables:
        return
    tbl = self._db.open_table(table_name)
    tbl.delete(f"doc_id = '{doc_id}'")
```

- [ ] **Step 5: Add `BM25Index.clear` to `src/piighost/indexer/retriever.py`**

Add this method inside the `BM25Index` class, after `load`:

```python
def clear(self) -> None:
    self._records = []
    self._bm25 = None
    if self._pkl_path.exists():
        self._pkl_path.unlink()
```

- [ ] **Step 6: Rewrite `index_path` in `src/piighost/service/core.py`**

Find the `index_path` method and replace it entirely:

```python
async def index_path(
    self, path: Path, *, recursive: bool = True, force: bool = False
) -> IndexReport:
    import time as _time

    from piighost.indexer.identity import content_hash

    start = _time.monotonic()
    paths = await list_document_paths(path, recursive=recursive)
    indexed = 0
    skipped = 0
    unchanged = 0
    errors: list[str] = []

    for p in paths:
        try:
            stat = p.stat()
            existing = self._vault.get_indexed_file_by_path(str(p))
            if not force and existing and abs(existing.mtime - stat.st_mtime) < 0.001:
                unchanged += 1
                continue

            text = await extract_text(p)
            if text is None:
                skipped += 1
                continue

            doc_id = content_hash(p)

            # Remove stale chunks for this path (old or same doc_id)
            if existing:
                self._chunk_store.delete_doc(existing.doc_id)
                if existing.doc_id != doc_id:
                    self._vault.delete_indexed_file(existing.doc_id)

            result = await self.anonymize(text, doc_id=doc_id)
            anon_text = result.anonymized
            chunks = chunk_text(anon_text)
            if not chunks:
                skipped += 1
                continue

            vectors = await self._embedder.embed(chunks)
            self._chunk_store.upsert_chunks(doc_id, str(p), chunks, vectors)
            self._vault.upsert_indexed_file(
                doc_id=doc_id,
                file_path=str(p),
                content_hash=doc_id,
                mtime=stat.st_mtime,
                chunk_count=len(chunks),
            )
            indexed += 1
        except Exception as exc:
            errors.append(f"{p}: {type(exc).__name__}")

    all_records = self._chunk_store.all_records()
    if all_records:
        self._bm25.rebuild(all_records)
    else:
        self._bm25.clear()

    duration_ms = int((_time.monotonic() - start) * 1000)
    return IndexReport(
        indexed=indexed,
        skipped=skipped,
        unchanged=unchanged,
        errors=errors,
        duration_ms=duration_ms,
    )
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_service_incremental.py -v -p no:randomly
```

Expected: 4 PASSED.

- [ ] **Step 8: Run full unit suite**

```bash
python -m pytest tests/unit/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 9: Commit**

```bash
git add src/piighost/service/models.py src/piighost/indexer/store.py \
        src/piighost/indexer/retriever.py src/piighost/service/core.py \
        tests/unit/test_service_incremental.py
git commit -m "feat(service): incremental index_path — mtime skip, content-hash doc_id, force flag"
```

---

### Task 4: `PIIGhostService.remove_doc`

**Files:**
- Modify: `src/piighost/service/core.py`
- Create: `tests/unit/test_service_remove_doc.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_service_remove_doc.py
import asyncio
import pytest
from pathlib import Path
from piighost.service.core import PIIGhostService


@pytest.fixture()
def indexed_svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault_dir = tmp_path / "vault"
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    f = tmp_path / "doc.txt"
    f.write_text("Alice works in Paris on legal contracts.")
    asyncio.run(svc.index_path(f))
    return svc, f


def test_remove_doc_returns_true_when_found(indexed_svc):
    svc, f = indexed_svc
    removed = asyncio.run(svc.remove_doc(f))
    assert removed is True
    asyncio.run(svc.close())


def test_remove_doc_returns_false_when_not_found(indexed_svc):
    svc, _ = indexed_svc
    removed = asyncio.run(svc.remove_doc(Path("/nonexistent/file.txt")))
    assert removed is False
    asyncio.run(svc.close())


def test_remove_doc_removes_from_indexed_files(indexed_svc):
    svc, f = indexed_svc
    asyncio.run(svc.remove_doc(f))
    assert svc._vault.get_indexed_file_by_path(str(f)) is None
    asyncio.run(svc.close())


def test_remove_doc_removes_chunks(indexed_svc):
    svc, f = indexed_svc
    assert len(svc._chunk_store.all_records()) >= 1
    asyncio.run(svc.remove_doc(f))
    assert svc._chunk_store.all_records() == []
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/test_service_remove_doc.py -v -p no:randomly
```

Expected: `AttributeError: 'PIIGhostService' object has no attribute 'remove_doc'`

- [ ] **Step 3: Add `remove_doc` to `src/piighost/service/core.py`**

Add this method after `index_path`:

```python
async def remove_doc(self, path: Path) -> bool:
    existing = self._vault.get_indexed_file_by_path(str(path.resolve()))
    if existing is None:
        return False
    self._chunk_store.delete_doc(existing.doc_id)
    self._vault.delete_doc_entities(existing.doc_id)
    self._vault.delete_indexed_file(existing.doc_id)
    all_records = self._chunk_store.all_records()
    if all_records:
        self._bm25.rebuild(all_records)
    else:
        self._bm25.clear()
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_service_remove_doc.py -v -p no:randomly
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_service_remove_doc.py
git commit -m "feat(service): remove_doc — delete chunks, doc_entities, indexed_files record"
```

---

### Task 5: `IndexStatus` model + `PIIGhostService.index_status`

**Files:**
- Modify: `src/piighost/service/models.py`
- Modify: `src/piighost/service/core.py`
- Create: `tests/unit/test_service_index_status.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_service_index_status.py
import asyncio
import pytest
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc_with_docs(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault_dir = tmp_path / "vault"
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works in Paris")
    (docs / "b.txt").write_text("Legal contracts are reviewed weekly")
    asyncio.run(svc.index_path(docs))
    return svc, docs


def test_index_status_total_docs(svc_with_docs):
    svc, _ = svc_with_docs
    status = asyncio.run(svc.index_status())
    assert status.total_docs == 2
    asyncio.run(svc.close())


def test_index_status_total_chunks(svc_with_docs):
    svc, _ = svc_with_docs
    status = asyncio.run(svc.index_status())
    assert status.total_chunks >= 2
    asyncio.run(svc.close())


def test_index_status_files_list(svc_with_docs):
    svc, docs = svc_with_docs
    status = asyncio.run(svc.index_status())
    paths = {f.file_path for f in status.files}
    assert str(docs / "a.txt") in paths
    assert str(docs / "b.txt") in paths
    asyncio.run(svc.close())


def test_index_status_empty_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    status = asyncio.run(svc.index_status())
    assert status.total_docs == 0
    assert status.total_chunks == 0
    assert status.files == []
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/test_service_index_status.py -v -p no:randomly
```

Expected: `AttributeError: 'PIIGhostService' object has no attribute 'index_status'`

- [ ] **Step 3: Add models to `src/piighost/service/models.py`**

Append after `QueryResult`:

```python
class IndexedFileEntry(BaseModel):
    doc_id: str
    file_path: str
    indexed_at: int
    chunk_count: int


class IndexStatus(BaseModel):
    total_docs: int
    total_chunks: int
    files: list[IndexedFileEntry]
```

- [ ] **Step 4: Add `index_status` to `src/piighost/service/core.py`**

Add the import at the top (in the `from piighost.service.models import` block):

```python
from piighost.service.models import (
    ...,   # existing imports
    IndexedFileEntry,
    IndexStatus,
)
```

Add the method after `remove_doc`:

```python
async def index_status(
    self, *, limit: int = 100, offset: int = 0
) -> IndexStatus:
    total_docs = self._vault.count_indexed_files()
    total_chunks = self._vault.total_chunk_count()
    files = self._vault.list_indexed_files(limit=limit, offset=offset)
    entries = [
        IndexedFileEntry(
            doc_id=f.doc_id,
            file_path=f.file_path,
            indexed_at=f.indexed_at,
            chunk_count=f.chunk_count,
        )
        for f in files
    ]
    return IndexStatus(
        total_docs=total_docs,
        total_chunks=total_chunks,
        files=entries,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_service_index_status.py -v -p no:randomly
```

Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/service/models.py src/piighost/service/core.py \
        tests/unit/test_service_index_status.py
git commit -m "feat(service): index_status — indexed file list with totals"
```

---

### Task 6: CLI `piighost rm` + `piighost index-status` + daemon dispatch

**Files:**
- Create: `src/piighost/cli/commands/rm.py`
- Create: `src/piighost/cli/commands/index_status.py`
- Modify: `src/piighost/cli/commands/index.py` (add `--force`)
- Modify: `src/piighost/cli/main.py`
- Modify: `src/piighost/daemon/server.py`
- Create: `tests/unit/test_cli_rm_status.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cli_rm_status.py
from typer.testing import CliRunner
from piighost.cli.main import app

runner = CliRunner()


def test_rm_help():
    result = runner.invoke(app, ["rm", "--help"])
    assert result.exit_code == 0
    assert "path" in result.output.lower()


def test_index_status_help():
    result = runner.invoke(app, ["index-status", "--help"])
    assert result.exit_code == 0


def test_index_force_flag():
    result = runner.invoke(app, ["index", "--help"])
    assert result.exit_code == 0
    assert "force" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/test_cli_rm_status.py -v -p no:randomly
```

Expected: `Exit code != 0` — commands not registered.

- [ ] **Step 3: Create `src/piighost/cli/commands/rm.py`**

```python
"""`piighost rm <path>` — remove a document from the index."""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from piighost.cli.commands.vault import _load_cfg, _resolve_vault
from piighost.cli.output import ExitCode, emit_error_line, emit_json_line
from piighost.daemon.client import DaemonClient
from piighost.exceptions import VaultNotFound
from piighost.service import PIIGhostService


def run(
    path: Path = typer.Argument(..., help="File to remove from the index"),
    vault: Path | None = typer.Option(None, "--vault"),
) -> None:
    try:
        vault_dir = _resolve_vault(vault)
    except VaultNotFound as exc:
        emit_error_line(
            error="VaultNotFound",
            message=str(exc),
            hint="Run `piighost init`",
            exit_code=ExitCode.USER_ERROR,
        )
        raise typer.Exit(code=int(ExitCode.USER_ERROR))

    client = DaemonClient.from_vault(vault_dir)
    if client is not None:
        result = client.call("remove_doc", {"path": str(path.resolve())})
        emit_json_line(result)
        return

    asyncio.run(_remove(vault_dir, path))


async def _remove(vault_dir: Path, path: Path) -> None:
    config = _load_cfg(vault_dir)
    svc = await PIIGhostService.create(vault_dir=vault_dir, config=config)
    try:
        removed = await svc.remove_doc(path.resolve())
        emit_json_line({"removed": removed})
    finally:
        await svc.close()
```

- [ ] **Step 4: Create `src/piighost/cli/commands/index_status.py`**

```python
"""`piighost index-status` — list indexed documents."""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from piighost.cli.commands.vault import _load_cfg, _resolve_vault
from piighost.cli.output import ExitCode, emit_error_line, emit_json_line
from piighost.daemon.client import DaemonClient
from piighost.exceptions import VaultNotFound
from piighost.service import PIIGhostService


def run(
    vault: Path | None = typer.Option(None, "--vault"),
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    try:
        vault_dir = _resolve_vault(vault)
    except VaultNotFound as exc:
        emit_error_line(
            error="VaultNotFound",
            message=str(exc),
            hint="Run `piighost init`",
            exit_code=ExitCode.USER_ERROR,
        )
        raise typer.Exit(code=int(ExitCode.USER_ERROR))

    client = DaemonClient.from_vault(vault_dir)
    if client is not None:
        result = client.call("index_status", {"limit": limit, "offset": offset})
        emit_json_line(result)
        return

    asyncio.run(_status(vault_dir, limit, offset))


async def _status(vault_dir: Path, limit: int, offset: int) -> None:
    config = _load_cfg(vault_dir)
    svc = await PIIGhostService.create(vault_dir=vault_dir, config=config)
    try:
        status = await svc.index_status(limit=limit, offset=offset)
        emit_json_line(status.model_dump())
    finally:
        await svc.close()
```

- [ ] **Step 5: Add `--force` to `src/piighost/cli/commands/index.py`**

Find the `run` function signature and add `force`:

```python
def run(
    path: Path = typer.Argument(..., help="File or directory to index"),
    vault: Path | None = typer.Option(None, "--vault"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
    force: bool = typer.Option(False, "--force/--no-force", help="Re-index even if unchanged"),
) -> None:
```

Update the daemon call to pass `force`:

```python
    if client is not None:
        result = client.call(
            "index_path",
            {"path": str(path.resolve()), "recursive": recursive, "force": force},
        )
        emit_json_line(result)
        return

    asyncio.run(_index(vault_dir, path, recursive, force))
```

Update `_index` signature and call:

```python
async def _index(vault_dir: Path, path: Path, recursive: bool, force: bool) -> None:
    config = _load_cfg(vault_dir)
    svc = await PIIGhostService.create(vault_dir=vault_dir, config=config)
    try:
        report = await svc.index_path(path.resolve(), recursive=recursive, force=force)
        emit_json_line(report.model_dump())
    finally:
        await svc.close()
```

- [ ] **Step 6: Register commands in `src/piighost/cli/main.py`**

Add these imports alongside the existing ones:

```python
from piighost.cli.commands import rm as rm_cmd
from piighost.cli.commands import index_status as index_status_cmd
```

Register them with the app (after existing `app.command` calls):

```python
app.command("rm")(rm_cmd.run)
app.command("index-status")(index_status_cmd.run)
```

- [ ] **Step 7: Add dispatch cases to `src/piighost/daemon/server.py`**

In the `_dispatch` function, after the existing `query` case, add:

```python
if method == "remove_doc":
    from pathlib import Path as _Path
    removed = await svc.remove_doc(_Path(params["path"]))
    return {"removed": removed}

if method == "index_status":
    status = await svc.index_status(
        limit=params.get("limit", 100),
        offset=params.get("offset", 0),
    )
    return status.model_dump()
```

Also update the existing `index_path` dispatch to pass `force`:

```python
if method == "index_path":
    from pathlib import Path as _Path
    report = await svc.index_path(
        _Path(params["path"]),
        recursive=params.get("recursive", True),
        force=params.get("force", False),
    )
    return report.model_dump()
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_cli_rm_status.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 9: Run full unit suite**

```bash
python -m pytest tests/unit/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 10: Commit**

```bash
git add src/piighost/cli/commands/rm.py \
        src/piighost/cli/commands/index_status.py \
        src/piighost/cli/commands/index.py \
        src/piighost/cli/main.py \
        src/piighost/daemon/server.py \
        tests/unit/test_cli_rm_status.py
git commit -m "feat(cli): piighost rm, piighost index-status, index --force flag"
```

---

### Task 7: E2E tests for incremental behavior

**Files:**
- Create: `tests/e2e/test_incremental_indexing.py`

- [ ] **Step 1: Write the tests**

```python
# tests/e2e/test_incremental_indexing.py
"""E2E: incremental indexing — skip unchanged, reindex modified, remove doc."""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault_dir = tmp_path / "vault"
    service = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    yield service
    asyncio.run(service.close())


@pytest.fixture()
def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "contract.txt").write_text(
        "Alice is a legal consultant. The project is based in Paris."
    )
    (d / "report.txt").write_text(
        "The data processing agreement was submitted to the Paris DPA office."
    )
    (d / "memo.txt").write_text(
        "A meeting concluded with approval. Alice will follow up."
    )
    return d


def test_second_index_skips_all_unchanged(svc, docs):
    r1 = asyncio.run(svc.index_path(docs))
    assert r1.indexed == 3
    assert r1.unchanged == 0

    r2 = asyncio.run(svc.index_path(docs))
    assert r2.indexed == 0
    assert r2.unchanged == 3
    assert r2.errors == []


def test_force_flag_reindexes_all(svc, docs):
    asyncio.run(svc.index_path(docs))
    r2 = asyncio.run(svc.index_path(docs, force=True))
    assert r2.indexed == 3
    assert r2.unchanged == 0


def test_modified_file_is_reindexed(svc, tmp_path):
    d = tmp_path / "docs2"
    d.mkdir()
    f = d / "doc.txt"
    f.write_text("Alice works in Paris on GDPR contracts.")

    r1 = asyncio.run(svc.index_path(f))
    assert r1.indexed == 1

    # Modify mtime explicitly so the skip check detects a change
    new_mtime = f.stat().st_mtime + 2.0
    os.utime(f, (new_mtime, new_mtime))

    r2 = asyncio.run(svc.index_path(f))
    assert r2.indexed == 1
    assert r2.unchanged == 0


def test_remove_doc_removes_from_query_results(svc, tmp_path):
    d = tmp_path / "docs3"
    d.mkdir()
    f = d / "doc.txt"
    f.write_text("Alice works in Paris on legal contracts and compliance reviews.")

    asyncio.run(svc.index_path(f))
    result_before = asyncio.run(svc.query("legal compliance", k=5))
    assert len(result_before.hits) >= 1

    asyncio.run(svc.remove_doc(f))
    result_after = asyncio.run(svc.query("legal compliance", k=5))
    assert len(result_after.hits) == 0


def test_index_status_reflects_indexed_files(svc, docs):
    asyncio.run(svc.index_path(docs))
    status = asyncio.run(svc.index_status())
    assert status.total_docs == 3
    assert status.total_chunks >= 3
    indexed_paths = {f.file_path for f in status.files}
    for name in ("contract.txt", "report.txt", "memo.txt"):
        assert str(docs / name) in indexed_paths


def test_remove_doc_updates_index_status(svc, docs):
    asyncio.run(svc.index_path(docs))
    asyncio.run(svc.remove_doc(docs / "contract.txt"))
    status = asyncio.run(svc.index_status())
    assert status.total_docs == 2
    paths = {f.file_path for f in status.files}
    assert str(docs / "contract.txt") not in paths
```

- [ ] **Step 2: Run E2E tests**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
python -m pytest tests/e2e/test_incremental_indexing.py -v -p no:randomly
```

Expected: 6 PASSED.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/unit/ tests/e2e/ -q -p no:randomly 2>&1 | tail -8
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_incremental_indexing.py
git commit -m "test(e2e): incremental indexing — skip/reindex/remove/status roundtrip"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|-------------|------|
| Skip unchanged files (mtime check) | Task 3 |
| Content-hash stable doc_id | Tasks 2 + 3 |
| `--force` flag to override skip | Tasks 3 + 6 |
| `piighost rm <path>` | Tasks 4 + 6 |
| Remove doc from chunks + doc_entities | Task 4 |
| `piighost index-status` | Tasks 5 + 6 |
| `IndexStatus` model with totals + file list | Task 5 |
| Daemon dispatch for `remove_doc`, `index_status` | Task 6 |
| E2E: skip unchanged | Task 7 |
| E2E: reindex modified | Task 7 |
| E2E: remove removes from query | Task 7 |
| E2E: index-status reflects reality | Task 7 |

**No placeholders found.** All steps contain complete code.

**Type consistency check:**
- `IndexedFileRecord` defined in Task 1, used in Tasks 3, 4, 5 via `Vault` methods — consistent.
- `content_hash(path) -> str` defined in Task 2, imported in Task 3 `index_path` — consistent.
- `IndexReport.unchanged` added in Task 3, read in Task 7 E2E tests — consistent.
- `IndexedFileEntry`, `IndexStatus` defined in Task 5, returned by `index_status()`, serialized in Task 6 CLI — consistent.
- `remove_doc(path: Path) -> bool` defined in Task 4, dispatched as `remove_doc` in Task 6 — consistent.
- `index_status(*, limit, offset) -> IndexStatus` defined in Task 5, dispatched in Task 6 — consistent.
- `ChunkStore.delete_doc(doc_id: str) -> None` added in Task 3, used in Tasks 4 — consistent.
- `BM25Index.clear() -> None` added in Task 3, used in Tasks 3 + 4 — consistent.
