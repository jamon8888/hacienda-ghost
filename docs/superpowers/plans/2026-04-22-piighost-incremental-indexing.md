# piighost Incremental Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade piighost's indexing pipeline from a silent mtime-only skip into a production-ready incremental indexer with SHA-256 fallback, per-file error isolation, tiered batch scheduling, and new MCP tools (`check_folder_changes`, `cancel_indexing`) — so users see new Cowork documents become searchable without re-paying NER/embeddings cost on unchanged files.

**Architecture:** A dedicated SQLite metadata store (`indexing.sqlite`) per project tracks `(file_path, mtime, size, content_hash, status, error_message, entity_count, chunk_count)` with a `schema_version` column. A pure `ChangeDetector` compares the current folder state vs. the store (mtime+size fast path; SHA-256 on mismatch) and returns classified sets `{new, modified, deleted, unchanged}`. A `BatchScheduler` tags each change set as small/medium/large. The existing `PIIGhostService.index_path` is refactored to run detection → schedule → per-file try/except indexing → transactional commit. Two new MCP tools expose the detector (`check_folder_changes`) and a cancellation flag (`cancel_indexing`). A migration reads the existing `vault.indexed_files` rows on first start of the new code and backfills the new store.

**Tech Stack:** Python 3.11+, FastMCP, pydantic v2, stdlib `sqlite3`, stdlib `hashlib`. Test stack: pytest, `PIIGHOST_DETECTOR=stub`, `PIIGHOST_EMBEDDER=stub`. All tests run under WSL (`wsl bash -c "cd /mnt/c/.../piighost && pytest ..."`) to stay consistent with project conventions.

---

## File Structure

### Create

- `src/piighost/indexer/indexing_store.py` — `IndexingStore` SQLite wrapper (new `indexing.sqlite` DB per project with the `indexed_files` schema from the spec). Owns DDL, migrations, and CRUD.
- `src/piighost/indexer/change_detector.py` — `ChangeDetector` (pure function + dataclass `ChangeSet`). mtime+size fast path, SHA-256 fallback.
- `src/piighost/indexer/batch_scheduler.py` — `classify_batch(change_set, config) -> BatchTier` enum + `BatchTier` classification.
- `src/piighost/indexer/cancellation.py` — `CancellationToken` (async-safe flag) + per-project registry.
- `tests/unit/indexer/test_indexing_store.py` — DDL, migrations, CRUD, rollback.
- `tests/unit/indexer/test_change_detector.py` — classification of new/modified/unchanged/deleted; hash-only-when-needed.
- `tests/unit/indexer/test_batch_scheduler.py` — tier classification edge cases.
- `tests/unit/indexer/test_cancellation.py` — token set/check semantics.
- `tests/unit/test_service_check_folder_changes.py` — service-level API.
- `tests/unit/test_service_incremental_v2.py` — upgraded incremental flow (modified ≠ new, per-file error isolation).
- `tests/unit/test_service_cancel_indexing.py` — cancellation service API.
- `tests/unit/test_mcp_check_folder_changes.py` — MCP tool wiring.
- `tests/unit/test_mcp_cancel_indexing.py` — MCP tool wiring.
- `tests/unit/test_indexing_store_migration.py` — vault→store backfill.
- `tests/e2e/test_incremental_indexing_v2.py` — end-to-end scenarios from spec (§Integration + §E2E).
- `tests/e2e/test_incremental_indexing_perf.py` — perf target (§Performance).

### Modify

- `src/piighost/indexer/identity.py` — add `file_fingerprint(path) -> (mtime, size)` helper and keep the existing `content_hash` (already returns 16-char SHA-256 prefix — spec calls for full SHA-256 hex, so widen to 64 chars).
- `src/piighost/service/config.py` — add `IncrementalSection` (thresholds for small/medium/large tiers, idle_timeout_sec already exists in daemon section).
- `src/piighost/service/models.py` — add pydantic models: `ChangeSetModel`, `FolderChangesResult`, `CancelResult`. Extend `IndexReport` with `modified: int`, `deleted: int`.
- `src/piighost/service/core.py` — refactor `_ProjectService.__init__` / `create` to own an `IndexingStore`. Rewrite `index_path` to use the detector + scheduler + per-file try/except, respecting the `CancellationToken`. Add `check_folder_changes`, `cancel_indexing`. Wire migration in `_get_project`.
- `src/piighost/mcp/server.py` — register `check_folder_changes`, `cancel_indexing` MCP tools; update `index_path` return schema.
- `src/piighost/vault/schema.py` — no changes to table (reads stay legacy-compatible), but add a migration NOOP marker comment so future readers know `indexed_files` is now read-only legacy + the truth lives in `indexing.sqlite`.

### Test (moved from existing)

- `tests/unit/test_service_incremental.py` — existing tests continue to pass (`unchanged`, `force=True`, `doc_id==content_hash`). Do not delete — they regression-lock the minimal behavior.
- `tests/e2e/test_incremental_indexing.py` — continues to pass. New e2e file adds the v2 scenarios.

---

## Task 1: IndexingStore — SQLite schema + open/close

**Files:**
- Create: `src/piighost/indexer/indexing_store.py`
- Test: `tests/unit/indexer/test_indexing_store.py`

**Context:** The spec's §1 defines a fresh `indexed_files` table in a dedicated per-project SQLite file. Start with the schema and a minimal `open()` that creates it idempotently. Don't add CRUD yet — a failing smoke test first.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_indexing_store.py
import sqlite3
from pathlib import Path
import pytest

from piighost.indexer.indexing_store import IndexingStore


def test_open_creates_schema(tmp_path: Path) -> None:
    db = tmp_path / "indexing.sqlite"
    store = IndexingStore.open(db)
    try:
        rows = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {r[0] for r in rows}
        assert "indexed_files" in tables
        assert "indexing_meta" in tables
    finally:
        store.close()


def test_open_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "indexing.sqlite"
    IndexingStore.open(db).close()
    store = IndexingStore.open(db)  # must not raise
    store.close()


def test_schema_version_stamped(tmp_path: Path) -> None:
    store = IndexingStore.open(tmp_path / "indexing.sqlite")
    try:
        (version,) = store._conn.execute(
            "SELECT version FROM indexing_meta WHERE singleton = 1"
        ).fetchone()
        assert version == 1
    finally:
        store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_indexing_store.py -v"`
Expected: FAIL with `ModuleNotFoundError: No module named 'piighost.indexer.indexing_store'`.

- [ ] **Step 3: Write the module**

```python
# src/piighost/indexer/indexing_store.py
"""Per-project metadata store for incremental indexing.

Separate SQLite file (``{project_dir}/indexing.sqlite``) so indexing
metadata does not pollute the PII vault schema.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

CURRENT_SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS indexed_files (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_mtime REAL NOT NULL,
    file_size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at REAL NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    entity_count INTEGER,
    chunk_count INTEGER,
    schema_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(project_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_indexed_files_project
    ON indexed_files(project_id);

CREATE INDEX IF NOT EXISTS idx_indexed_files_status
    ON indexed_files(project_id, status);

CREATE TABLE IF NOT EXISTS indexing_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
"""


class IndexingStore:
    """Per-project incremental-indexing metadata.

    One ``IndexingStore`` per SQLite file. Safe for single-connection use
    only; each ``_ProjectService`` owns one instance.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, db_path: Path) -> "IndexingStore":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_DDL)
        cur = conn.execute("SELECT COUNT(*) FROM indexing_meta")
        if cur.fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO indexing_meta (singleton, version, created_at)"
                " VALUES (1, ?, ?)",
                (CURRENT_SCHEMA_VERSION, int(time.time())),
            )
        return cls(conn)

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_indexing_store.py -v"`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/indexer/indexing_store.py tests/unit/indexer/test_indexing_store.py
git commit -m "feat(indexer): introduce IndexingStore with per-project schema"
```

---

## Task 2: IndexingStore — CRUD for file records

**Files:**
- Modify: `src/piighost/indexer/indexing_store.py`
- Test: `tests/unit/indexer/test_indexing_store.py`

**Context:** Add the dataclass + insert/upsert/read/delete/list methods the detector and indexer need. Keep methods small and explicit.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/indexer/test_indexing_store.py`:

```python
from piighost.indexer.indexing_store import FileRecord


def _make_store(tmp_path):
    return IndexingStore.open(tmp_path / "indexing.sqlite")


def test_upsert_then_get_by_path(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    try:
        store.upsert(FileRecord(
            project_id="proj",
            file_path="/abs/a.txt",
            file_mtime=1000.5,
            file_size=42,
            content_hash="a" * 64,
            indexed_at=1700000000.0,
            status="success",
            error_message=None,
            entity_count=3,
            chunk_count=2,
        ))
        got = store.get_by_path("proj", "/abs/a.txt")
        assert got is not None
        assert got.file_size == 42
        assert got.content_hash == "a" * 64
        assert got.status == "success"
        assert got.entity_count == 3
    finally:
        store.close()


def test_upsert_replaces_same_path(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    try:
        rec = FileRecord(
            project_id="proj", file_path="/abs/a.txt",
            file_mtime=1.0, file_size=1, content_hash="x" * 64,
            indexed_at=1.0, status="success",
            error_message=None, entity_count=0, chunk_count=0,
        )
        store.upsert(rec)
        store.upsert(rec.__class__(**{**rec.__dict__, "file_size": 99, "content_hash": "y" * 64}))
        got = store.get_by_path("proj", "/abs/a.txt")
        assert got.file_size == 99
        assert got.content_hash == "y" * 64
        (count,) = store._conn.execute(
            "SELECT COUNT(*) FROM indexed_files WHERE project_id='proj'"
        ).fetchone()
        assert count == 1
    finally:
        store.close()


def test_list_for_project_isolates_projects(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    try:
        def rec(pid, path):
            return FileRecord(
                project_id=pid, file_path=path,
                file_mtime=1.0, file_size=1, content_hash="x" * 64,
                indexed_at=1.0, status="success",
                error_message=None, entity_count=0, chunk_count=0,
            )
        store.upsert(rec("a", "/p/1"))
        store.upsert(rec("a", "/p/2"))
        store.upsert(rec("b", "/p/3"))
        assert len(store.list_for_project("a")) == 2
        assert len(store.list_for_project("b")) == 1
    finally:
        store.close()


def test_delete_by_path(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    try:
        store.upsert(FileRecord(
            project_id="p", file_path="/x",
            file_mtime=1.0, file_size=1, content_hash="h" * 64,
            indexed_at=1.0, status="success",
            error_message=None, entity_count=0, chunk_count=0,
        ))
        assert store.delete_by_path("p", "/x") is True
        assert store.get_by_path("p", "/x") is None
        assert store.delete_by_path("p", "/x") is False
    finally:
        store.close()


def test_mark_deleted_sets_status(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    try:
        store.upsert(FileRecord(
            project_id="p", file_path="/x",
            file_mtime=1.0, file_size=1, content_hash="h" * 64,
            indexed_at=1.0, status="success",
            error_message=None, entity_count=0, chunk_count=0,
        ))
        store.mark_deleted("p", "/x")
        got = store.get_by_path("p", "/x")
        assert got is not None
        assert got.status == "deleted"
    finally:
        store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_indexing_store.py -v"`
Expected: the 5 new tests fail with `ImportError: cannot import name 'FileRecord'` or `AttributeError`.

- [ ] **Step 3: Extend the module**

Append to `src/piighost/indexer/indexing_store.py`:

```python
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class FileRecord:
    project_id: str
    file_path: str
    file_mtime: float
    file_size: int
    content_hash: str
    indexed_at: float
    status: str                  # 'success' | 'error' | 'deleted'
    error_message: str | None
    entity_count: int | None
    chunk_count: int | None


def _row_to_record(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        project_id=row["project_id"],
        file_path=row["file_path"],
        file_mtime=row["file_mtime"],
        file_size=row["file_size"],
        content_hash=row["content_hash"],
        indexed_at=row["indexed_at"],
        status=row["status"],
        error_message=row["error_message"],
        entity_count=row["entity_count"],
        chunk_count=row["chunk_count"],
    )


# ---- CRUD methods on IndexingStore ----

def _upsert(self, rec: FileRecord) -> None:  # noqa: N805
    self._conn.execute(
        """
        INSERT INTO indexed_files (
            project_id, file_path, file_mtime, file_size, content_hash,
            indexed_at, status, error_message, entity_count, chunk_count,
            schema_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, file_path) DO UPDATE SET
            file_mtime     = excluded.file_mtime,
            file_size      = excluded.file_size,
            content_hash   = excluded.content_hash,
            indexed_at     = excluded.indexed_at,
            status         = excluded.status,
            error_message  = excluded.error_message,
            entity_count   = excluded.entity_count,
            chunk_count    = excluded.chunk_count
        """,
        (
            rec.project_id, rec.file_path, rec.file_mtime, rec.file_size,
            rec.content_hash, rec.indexed_at, rec.status,
            rec.error_message, rec.entity_count, rec.chunk_count,
            CURRENT_SCHEMA_VERSION,
        ),
    )


def _get_by_path(self, project_id: str, file_path: str) -> FileRecord | None:  # noqa: N805
    row = self._conn.execute(
        "SELECT * FROM indexed_files WHERE project_id = ? AND file_path = ?",
        (project_id, file_path),
    ).fetchone()
    return _row_to_record(row) if row else None


def _list_for_project(self, project_id: str) -> list[FileRecord]:  # noqa: N805
    rows = self._conn.execute(
        "SELECT * FROM indexed_files WHERE project_id = ?", (project_id,)
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def _delete_by_path(self, project_id: str, file_path: str) -> bool:  # noqa: N805
    cur = self._conn.execute(
        "DELETE FROM indexed_files WHERE project_id = ? AND file_path = ?",
        (project_id, file_path),
    )
    return cur.rowcount > 0


def _mark_deleted(self, project_id: str, file_path: str) -> None:  # noqa: N805
    self._conn.execute(
        "UPDATE indexed_files SET status = 'deleted'"
        " WHERE project_id = ? AND file_path = ?",
        (project_id, file_path),
    )


IndexingStore.upsert = _upsert
IndexingStore.get_by_path = _get_by_path
IndexingStore.list_for_project = _list_for_project
IndexingStore.delete_by_path = _delete_by_path
IndexingStore.mark_deleted = _mark_deleted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_indexing_store.py -v"`
Expected: 8 passed (3 from Task 1 + 5 new).

- [ ] **Step 5: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/indexer/indexing_store.py tests/unit/indexer/test_indexing_store.py
git commit -m "feat(indexer): IndexingStore CRUD (upsert/get/list/delete/mark_deleted)"
```

---

## Task 3: IndexingStore — transactional batch + rollback

**Files:**
- Modify: `src/piighost/indexer/indexing_store.py`
- Test: `tests/unit/indexer/test_indexing_store.py`

**Context:** Per spec §4, a batch must either fully commit or fully roll back. Provide a `batch()` context manager that opens a `BEGIN IMMEDIATE` transaction and commits on success / rolls back on exception. Per-file errors do not raise — they get recorded as rows with `status='error'`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/indexer/test_indexing_store.py`:

```python
def test_batch_commits_on_success(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    try:
        with store.batch():
            store.upsert(FileRecord(
                project_id="p", file_path="/a",
                file_mtime=1.0, file_size=1, content_hash="h" * 64,
                indexed_at=1.0, status="success",
                error_message=None, entity_count=1, chunk_count=1,
            ))
        assert store.get_by_path("p", "/a") is not None
    finally:
        store.close()


def test_batch_rolls_back_on_exception(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    try:
        with pytest.raises(RuntimeError):
            with store.batch():
                store.upsert(FileRecord(
                    project_id="p", file_path="/a",
                    file_mtime=1.0, file_size=1, content_hash="h" * 64,
                    indexed_at=1.0, status="success",
                    error_message=None, entity_count=1, chunk_count=1,
                ))
                raise RuntimeError("boom")
        assert store.get_by_path("p", "/a") is None
    finally:
        store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_indexing_store.py::test_batch_commits_on_success tests/unit/indexer/test_indexing_store.py::test_batch_rolls_back_on_exception -v"`
Expected: FAIL — `AttributeError: 'IndexingStore' object has no attribute 'batch'`.

- [ ] **Step 3: Extend the module**

Append to `src/piighost/indexer/indexing_store.py`:

```python
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def _batch(self) -> Iterator[None]:  # noqa: N805
    # ``isolation_level=None`` ⇒ autocommit. Use explicit BEGIN/COMMIT.
    self._conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        self._conn.execute("ROLLBACK")
        raise
    else:
        self._conn.execute("COMMIT")


IndexingStore.batch = _batch
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_indexing_store.py -v"`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/indexer/indexing_store.py tests/unit/indexer/test_indexing_store.py
git commit -m "feat(indexer): IndexingStore transactional batch context manager"
```

---

## Task 4: identity.py — widen hash + add file_fingerprint

**Files:**
- Modify: `src/piighost/indexer/identity.py`
- Test: `tests/unit/indexer/test_identity.py`

**Context:** Spec §1 stores full SHA-256 hex (64 chars). Current `content_hash` returns a 16-char prefix. Widening is a breaking change for existing `doc_id` values — we will keep `content_hash` at the full 64 chars and derive a short `doc_id` separately where needed. Also add `file_fingerprint(path) -> (mtime, size)` for the fast path.

⚠️ Downstream coupling: `content_hash(path)` is currently used as `doc_id` in `service/core.py::index_path`. Existing stored doc_ids in LanceDB are 16-char. To avoid breaking live indexes, we add a new `content_hash_full(path)` returning 64 chars for the IndexingStore and keep `content_hash` returning the 16-char prefix (so `doc_id` stays stable).

- [ ] **Step 1: Write the failing test**

Update `tests/unit/indexer/test_identity.py`:

```python
from pathlib import Path

from piighost.indexer.identity import content_hash, content_hash_full, file_fingerprint


def test_content_hash_unchanged_is_16_chars(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello")
    h = content_hash(f)
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_content_hash_full_is_64_chars(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello")
    h = content_hash_full(f)
    assert len(h) == 64
    assert h.startswith(content_hash(f))


def test_file_fingerprint_returns_mtime_and_size(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello")
    mtime, size = file_fingerprint(f)
    stat = f.stat()
    assert mtime == stat.st_mtime
    assert size == stat.st_size == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_identity.py -v"`
Expected: FAIL on `content_hash_full` and `file_fingerprint` imports.

- [ ] **Step 3: Update identity.py**

Rewrite `src/piighost/indexer/identity.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path


def content_hash_full(path: Path) -> str:
    """Full 64-char SHA-256 hex digest of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def content_hash(path: Path) -> str:
    """16-char SHA-256 prefix used as ``doc_id``. Kept stable for back-compat."""
    return content_hash_full(path)[:16]


def file_fingerprint(path: Path) -> tuple[float, int]:
    """Cheap O(1) stat-based fingerprint: ``(mtime, size)``.

    The detector's fast path uses this; SHA-256 is only computed when
    mtime or size has changed.
    """
    stat = path.stat()
    return stat.st_mtime, stat.st_size
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_identity.py -v"`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/indexer/identity.py tests/unit/indexer/test_identity.py
git commit -m "feat(indexer): add content_hash_full + file_fingerprint helpers"
```

---

## Task 5: ChangeDetector — classify new/modified/unchanged/deleted

**Files:**
- Create: `src/piighost/indexer/change_detector.py`
- Test: `tests/unit/indexer/test_change_detector.py`

**Context:** Spec §2. Pure function over `(folder, project_id, store, supported_extensions)` returning a `ChangeSet`. Only call SHA-256 when mtime or size diverges. Verify the "don't hash when stat matches" invariant with a spy.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_change_detector.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from piighost.indexer.change_detector import ChangeDetector, ChangeSet
from piighost.indexer.indexing_store import IndexingStore, FileRecord


@pytest.fixture()
def store(tmp_path):
    s = IndexingStore.open(tmp_path / "indexing.sqlite")
    yield s
    s.close()


def _seed(store, project, path, mtime, size, chash):
    store.upsert(FileRecord(
        project_id=project, file_path=str(path),
        file_mtime=mtime, file_size=size, content_hash=chash,
        indexed_at=1.0, status="success",
        error_message=None, entity_count=0, chunk_count=1,
    ))


def test_new_file_is_classified_new(tmp_path, store):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.txt").write_text("hello")
    det = ChangeDetector(store=store, project_id="p")
    cs = det.scan(folder)
    assert [p.name for p in cs.new] == ["a.txt"]
    assert cs.modified == []
    assert cs.deleted == []
    assert cs.unchanged == []


def test_unchanged_file_when_mtime_and_size_match(tmp_path, store):
    folder = tmp_path / "docs"; folder.mkdir()
    f = folder / "a.txt"; f.write_text("hello")
    stat = f.stat()
    _seed(store, "p", f.resolve(), stat.st_mtime, stat.st_size, "x" * 64)
    det = ChangeDetector(store=store, project_id="p")
    # Spy on content_hash_full to ensure it is NOT called
    with patch("piighost.indexer.change_detector.content_hash_full") as spy:
        cs = det.scan(folder)
        spy.assert_not_called()
    assert cs.unchanged == [f.resolve()]
    assert cs.new == cs.modified == cs.deleted == []


def test_mtime_touched_but_content_unchanged_is_unchanged(tmp_path, store):
    folder = tmp_path / "docs"; folder.mkdir()
    f = folder / "a.txt"; f.write_text("hello")
    from piighost.indexer.identity import content_hash_full
    true_hash = content_hash_full(f)
    # seed with OLD mtime so stat check fails → forces hash
    _seed(store, "p", f.resolve(), 1.0, f.stat().st_size, true_hash)
    det = ChangeDetector(store=store, project_id="p")
    cs = det.scan(folder)
    assert cs.unchanged == [f.resolve()]
    assert cs.modified == []


def test_size_differs_triggers_modified(tmp_path, store):
    folder = tmp_path / "docs"; folder.mkdir()
    f = folder / "a.txt"; f.write_text("hello")
    _seed(store, "p", f.resolve(), f.stat().st_mtime, 999, "z" * 64)
    det = ChangeDetector(store=store, project_id="p")
    cs = det.scan(folder)
    assert cs.modified == [f.resolve()]
    assert cs.new == cs.unchanged == cs.deleted == []


def test_deleted_file_is_reported(tmp_path, store):
    folder = tmp_path / "docs"; folder.mkdir()
    missing = (folder / "gone.txt").resolve()
    _seed(store, "p", missing, 1.0, 1, "x" * 64)
    det = ChangeDetector(store=store, project_id="p")
    cs = det.scan(folder)
    assert cs.deleted == [missing]


def test_deleted_rows_with_status_deleted_are_not_re_reported(tmp_path, store):
    folder = tmp_path / "docs"; folder.mkdir()
    missing = (folder / "gone.txt").resolve()
    store.upsert(FileRecord(
        project_id="p", file_path=str(missing),
        file_mtime=1.0, file_size=1, content_hash="x" * 64,
        indexed_at=1.0, status="deleted",
        error_message=None, entity_count=None, chunk_count=None,
    ))
    det = ChangeDetector(store=store, project_id="p")
    cs = det.scan(folder)
    assert cs.deleted == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_change_detector.py -v"`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the module**

```python
# src/piighost/indexer/change_detector.py
"""Detect new / modified / unchanged / deleted files for a project.

Pure and side-effect-free: reads the filesystem + IndexingStore, returns
a :class:`ChangeSet`. The indexer is responsible for acting on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from piighost.indexer.identity import content_hash_full, file_fingerprint
from piighost.indexer.indexing_store import IndexingStore
from piighost.indexer.ingestor import list_document_paths

_STAT_EPSILON = 0.001  # seconds; tolerate FS mtime rounding


@dataclass(frozen=True)
class ChangeSet:
    new: list[Path] = field(default_factory=list)
    modified: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)

    def total_changes(self) -> int:
        return len(self.new) + len(self.modified) + len(self.deleted)


class ChangeDetector:
    def __init__(self, *, store: IndexingStore, project_id: str) -> None:
        self._store = store
        self._project_id = project_id

    async def scan_async(self, folder: Path, *, recursive: bool = True) -> ChangeSet:
        paths = await list_document_paths(folder, recursive=recursive)
        return self._classify(paths)

    def scan(self, folder: Path, *, recursive: bool = True) -> ChangeSet:
        # sync wrapper for tests; shells out to glob
        import asyncio
        return asyncio.run(self.scan_async(folder, recursive=recursive))

    def _classify(self, paths: list[Path]) -> ChangeSet:
        on_disk = {p.resolve() for p in paths}
        indexed = {
            r.file_path: r
            for r in self._store.list_for_project(self._project_id)
            if r.status != "deleted"
        }

        new: list[Path] = []
        modified: list[Path] = []
        unchanged: list[Path] = []

        for p in sorted(on_disk):
            key = str(p)
            rec = indexed.pop(key, None)
            if rec is None:
                new.append(p)
                continue
            mtime, size = file_fingerprint(p)
            if abs(mtime - rec.file_mtime) < _STAT_EPSILON and size == rec.file_size:
                unchanged.append(p)
                continue
            # fall back to content hash
            if content_hash_full(p) == rec.content_hash:
                unchanged.append(p)
            else:
                modified.append(p)

        # Whatever remains in ``indexed`` after popping disk matches is deleted
        deleted = [Path(k) for k in sorted(indexed.keys())]
        return ChangeSet(new=new, modified=modified, unchanged=unchanged, deleted=deleted)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_change_detector.py -v"`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/indexer/change_detector.py tests/unit/indexer/test_change_detector.py
git commit -m "feat(indexer): ChangeDetector with mtime+size fast path and hash fallback"
```

---

## Task 6: BatchScheduler — tier classification

**Files:**
- Modify: `src/piighost/service/config.py`
- Create: `src/piighost/indexer/batch_scheduler.py`
- Test: `tests/unit/indexer/test_batch_scheduler.py`

**Context:** Spec §3 defines three tiers by count and total size. Keep thresholds in `ServiceConfig.incremental` so they are deployment-tunable. The scheduler is a pure function: it does NOT make the ask-the-user decision — it only tags the tier. The ask loop lives in the core service (Task 10).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_batch_scheduler.py
from pathlib import Path

import pytest

from piighost.indexer.batch_scheduler import BatchTier, classify_batch
from piighost.indexer.change_detector import ChangeSet
from piighost.service.config import IncrementalSection


def _files(tmp_path, sizes):
    out = []
    for i, size in enumerate(sizes):
        f = tmp_path / f"f{i}.txt"
        f.write_bytes(b"x" * size)
        out.append(f)
    return out


def test_no_changes_is_empty(tmp_path):
    cs = ChangeSet()
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.EMPTY


def test_two_small_files_is_small(tmp_path):
    files = _files(tmp_path, [1024, 2048])
    cs = ChangeSet(new=files)
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.SMALL


def test_five_files_is_medium(tmp_path):
    files = _files(tmp_path, [100] * 5)
    cs = ChangeSet(new=files)
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.MEDIUM


def test_twenty_files_is_large(tmp_path):
    files = _files(tmp_path, [10] * 20)
    cs = ChangeSet(new=files)
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.LARGE


def test_large_total_size_triggers_large(tmp_path):
    # 2 files but total 60 MB → large
    big = tmp_path / "big.bin"
    big.write_bytes(b"\0" * (60 * 1024 * 1024))
    small = tmp_path / "s.txt"
    small.write_bytes(b"x")
    cs = ChangeSet(new=[big, small])
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.LARGE


def test_modified_counted_same_as_new(tmp_path):
    files = _files(tmp_path, [100] * 5)
    cs = ChangeSet(modified=files)
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.MEDIUM
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_batch_scheduler.py -v"`
Expected: FAIL — modules do not exist.

- [ ] **Step 3: Extend config with IncrementalSection**

Edit `src/piighost/service/config.py`, add before `class ServiceConfig`:

```python
class IncrementalSection(BaseModel):
    """Tiered batch thresholds for incremental indexing.

    Tiers from the incremental-indexing spec:
      - SMALL  : <= small_max_files AND total size <  medium_min_bytes
      - MEDIUM : <= medium_max_files OR  total size <= medium_max_bytes
      - LARGE  : anything bigger
    """

    small_max_files: int = 2
    small_max_bytes: int = 5 * 1024 * 1024           # 5 MB
    medium_max_files: int = 10
    medium_max_bytes: int = 50 * 1024 * 1024          # 50 MB
```

Add the field to `ServiceConfig`:

```python
incremental: IncrementalSection = Field(default_factory=IncrementalSection)
```

- [ ] **Step 4: Write the scheduler**

```python
# src/piighost/indexer/batch_scheduler.py
"""Classify a ChangeSet into a processing tier (small / medium / large)."""

from __future__ import annotations

import enum
from pathlib import Path

from piighost.indexer.change_detector import ChangeSet
from piighost.service.config import IncrementalSection


class BatchTier(str, enum.Enum):
    EMPTY = "empty"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


def _total_size(paths: list[Path]) -> int:
    total = 0
    for p in paths:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def classify_batch(cs: ChangeSet, config: IncrementalSection) -> BatchTier:
    payload = cs.new + cs.modified
    n = len(payload)
    if n == 0 and not cs.deleted:
        return BatchTier.EMPTY
    total = _total_size(payload)

    if n <= config.small_max_files and total < config.small_max_bytes:
        return BatchTier.SMALL
    if n <= config.medium_max_files and total <= config.medium_max_bytes:
        return BatchTier.MEDIUM
    return BatchTier.LARGE
```

- [ ] **Step 5: Run tests**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_batch_scheduler.py -v"`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/service/config.py src/piighost/indexer/batch_scheduler.py tests/unit/indexer/test_batch_scheduler.py
git commit -m "feat(indexer): BatchScheduler tier classification (small/medium/large)"
```

---

## Task 7: CancellationToken + registry

**Files:**
- Create: `src/piighost/indexer/cancellation.py`
- Test: `tests/unit/indexer/test_cancellation.py`

**Context:** Spec §5: `cancel_indexing(project)` sets a flag. The indexer checks it between files (not mid-NER — can't kill inference cleanly). Registry keyed by project name, process-local.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/indexer/test_cancellation.py
from piighost.indexer.cancellation import (
    CancellationToken,
    CancellationRegistry,
)


def test_token_is_not_cancelled_by_default():
    tok = CancellationToken()
    assert tok.is_cancelled is False


def test_cancel_sets_flag():
    tok = CancellationToken()
    tok.cancel()
    assert tok.is_cancelled is True


def test_registry_returns_same_token_for_same_project():
    reg = CancellationRegistry()
    t1 = reg.get_or_create("proj-a")
    t2 = reg.get_or_create("proj-a")
    assert t1 is t2


def test_registry_reset_replaces_token():
    reg = CancellationRegistry()
    t1 = reg.get_or_create("proj-a")
    t1.cancel()
    t2 = reg.reset("proj-a")
    assert t2 is not t1
    assert t2.is_cancelled is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_cancellation.py -v"`
Expected: FAIL.

- [ ] **Step 3: Write the module**

```python
# src/piighost/indexer/cancellation.py
"""Per-project cancellation tokens for the indexer."""

from __future__ import annotations

import threading


class CancellationToken:
    def __init__(self) -> None:
        self._flag = False

    @property
    def is_cancelled(self) -> bool:
        return self._flag

    def cancel(self) -> None:
        self._flag = True


class CancellationRegistry:
    def __init__(self) -> None:
        self._tokens: dict[str, CancellationToken] = {}
        self._lock = threading.Lock()

    def get_or_create(self, project: str) -> CancellationToken:
        with self._lock:
            tok = self._tokens.get(project)
            if tok is None:
                tok = CancellationToken()
                self._tokens[project] = tok
            return tok

    def reset(self, project: str) -> CancellationToken:
        with self._lock:
            tok = CancellationToken()
            self._tokens[project] = tok
            return tok
```

- [ ] **Step 4: Run tests**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/indexer/test_cancellation.py -v"`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/indexer/cancellation.py tests/unit/indexer/test_cancellation.py
git commit -m "feat(indexer): CancellationToken + per-project registry"
```

---

## Task 8: Service — extend models + wire IndexingStore into _ProjectService

**Files:**
- Modify: `src/piighost/service/models.py`
- Modify: `src/piighost/service/core.py`
- Test: no new test yet — regression via `tests/unit/test_service_incremental.py` and `tests/e2e/test_incremental_indexing.py` must still pass.

**Context:** Open the new `IndexingStore` alongside the existing vault, and extend `IndexReport` with `modified` and `deleted`. Don't touch `index_path` yet — Task 10 rewrites it. This task is a no-op wiring that keeps all existing tests green.

- [ ] **Step 1: Extend service models**

Edit `src/piighost/service/models.py`. Update `IndexReport`:

```python
class IndexReport(BaseModel):
    indexed: int
    modified: int = 0
    deleted: int = 0
    skipped: int
    unchanged: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_ms: int
    project: str = "default"
```

Append two new models at the bottom:

```python
class FileChangeEntry(BaseModel):
    file_path: str
    size: int


class FolderChangesResult(BaseModel):
    folder: str
    project: str
    new: list[FileChangeEntry] = Field(default_factory=list)
    modified: list[FileChangeEntry] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    unchanged_count: int = 0
    tier: str = "empty"   # BatchTier value


class CancelResult(BaseModel):
    project: str
    cancelled: bool
    files_processed: int = 0
    files_skipped: int = 0
```

- [ ] **Step 2: Wire IndexingStore into _ProjectService**

Edit `src/piighost/service/core.py`:

- Add import at top:
  ```python
  from piighost.indexer.indexing_store import IndexingStore
  from piighost.indexer.cancellation import CancellationToken, CancellationRegistry
  ```
- In `_ProjectService.__init__`, right after `self._bm25.load()`:
  ```python
  self._indexing_store = IndexingStore.open(
      self._project_dir / "indexing.sqlite"
  )
  self._cancel_token: CancellationToken | None = None
  ```
- In `_ProjectService.close`, before the vault close:
  ```python
  self._indexing_store.close()
  ```
- In the `PIIGhostService.__init__`, add:
  ```python
  self._cancel_registry = CancellationRegistry()
  ```

- [ ] **Step 3: Run full regression suite**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_service_incremental.py tests/e2e/test_incremental_indexing.py tests/unit/test_service_index.py tests/unit/test_service_index_status.py -v"`
Expected: all existing tests still PASS. No behavior change; the new store is opened but unused.

- [ ] **Step 4: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/service/models.py src/piighost/service/core.py
git commit -m "refactor(service): wire IndexingStore + CancellationRegistry (no-op)"
```

---

## Task 9: Migration — backfill IndexingStore from legacy vault.indexed_files

**Files:**
- Modify: `src/piighost/indexer/indexing_store.py`
- Test: `tests/unit/test_indexing_store_migration.py`

**Context:** Spec §6. On first open of `indexing.sqlite` for a project that already has data in `vault.indexed_files`, copy each row into the new store with `status='success'`, preserving `doc_id`, `mtime`, and `content_hash`. `file_size` comes from `Path.stat()` if the file still exists; if the file is missing, mark `status='deleted'` and `file_size=0`. Run this backfill only once (guarded by a row in `indexing_meta`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_indexing_store_migration.py
from __future__ import annotations

import time
from pathlib import Path

import pytest

from piighost.indexer.indexing_store import IndexingStore, backfill_from_vault
from piighost.vault.store import Vault


def test_backfill_copies_rows_from_vault(tmp_path):
    # 1. Seed a vault with an indexed_files row and a real file on disk
    vault_path = tmp_path / "vault.db"
    real = tmp_path / "real.txt"
    real.write_text("hello world")
    v = Vault.open(vault_path)
    v.upsert_indexed_file(
        doc_id="abc123def4567890",
        file_path=str(real),
        content_hash="abc123def4567890",
        mtime=real.stat().st_mtime,
        chunk_count=2,
    )
    v.close()

    # 2. Open a fresh IndexingStore, run backfill
    store = IndexingStore.open(tmp_path / "indexing.sqlite")
    try:
        v2 = Vault.open(vault_path)
        n = backfill_from_vault(store, v2, project_id="p")
        v2.close()
        assert n == 1
        rec = store.get_by_path("p", str(real))
        assert rec is not None
        assert rec.status == "success"
        assert rec.content_hash == "abc123def4567890"
        assert rec.file_size == real.stat().st_size
        assert rec.chunk_count == 2
    finally:
        store.close()


def test_backfill_marks_missing_files_deleted(tmp_path):
    vault_path = tmp_path / "vault.db"
    v = Vault.open(vault_path)
    v.upsert_indexed_file(
        doc_id="deadbeefdeadbeef",
        file_path=str(tmp_path / "gone.txt"),
        content_hash="deadbeefdeadbeef",
        mtime=1.0,
        chunk_count=1,
    )
    v.close()

    store = IndexingStore.open(tmp_path / "indexing.sqlite")
    try:
        v2 = Vault.open(vault_path)
        backfill_from_vault(store, v2, project_id="p")
        v2.close()
        rec = store.get_by_path("p", str(tmp_path / "gone.txt"))
        assert rec is not None
        assert rec.status == "deleted"
        assert rec.file_size == 0
    finally:
        store.close()


def test_backfill_idempotent(tmp_path):
    vault_path = tmp_path / "vault.db"
    real = tmp_path / "r.txt"
    real.write_text("x")
    v = Vault.open(vault_path)
    v.upsert_indexed_file(
        doc_id="1234567890abcdef",
        file_path=str(real),
        content_hash="1234567890abcdef",
        mtime=real.stat().st_mtime,
        chunk_count=1,
    )
    v.close()

    store = IndexingStore.open(tmp_path / "indexing.sqlite")
    try:
        v2 = Vault.open(vault_path)
        first = backfill_from_vault(store, v2, project_id="p")
        second = backfill_from_vault(store, v2, project_id="p")
        v2.close()
        assert first == 1
        assert second == 0   # second call is a no-op
    finally:
        store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_indexing_store_migration.py -v"`
Expected: FAIL — `backfill_from_vault` not defined.

- [ ] **Step 3: Implement backfill**

Append to `src/piighost/indexer/indexing_store.py`:

```python
def backfill_from_vault(
    store: IndexingStore, vault, project_id: str
) -> int:
    """One-shot migration: copy ``vault.indexed_files`` rows into ``store``.

    Safe to call repeatedly — records a ``backfill_done`` flag in
    ``indexing_meta``. Returns the number of rows copied on this call
    (0 on subsequent calls).
    """
    row = store._conn.execute(
        "SELECT value FROM indexing_kv WHERE key = 'backfill_done'"
    ).fetchone() if _has_kv(store) else None
    if row is not None:
        return 0

    _ensure_kv_table(store)
    inserted = 0
    with store.batch():
        for r in vault.list_indexed_files(limit=100_000, offset=0):
            path = Path(r.file_path)
            if path.exists():
                size = path.stat().st_size
                status = "success"
            else:
                size = 0
                status = "deleted"
            # Use the vault's content_hash (may be 16-char legacy); we pad
            # to the new column width so the detector's equality check
            # still works against freshly hashed files going forward only
            # when the file is re-indexed (legacy rows stay matchable by
            # their original 16-char hash via _content_hash_matches).
            chash = r.content_hash
            store.upsert(FileRecord(
                project_id=project_id,
                file_path=str(path),
                file_mtime=r.mtime,
                file_size=size,
                content_hash=chash,
                indexed_at=float(r.indexed_at),
                status=status,
                error_message=None,
                entity_count=None,
                chunk_count=r.chunk_count,
            ))
            inserted += 1
        store._conn.execute(
            "INSERT OR REPLACE INTO indexing_kv (key, value) VALUES ('backfill_done', '1')"
        )
    return inserted


def _ensure_kv_table(store: IndexingStore) -> None:
    store._conn.execute(
        "CREATE TABLE IF NOT EXISTS indexing_kv ("
        "  key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def _has_kv(store: IndexingStore) -> bool:
    row = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='indexing_kv'"
    ).fetchone()
    return row is not None
```

Note on detector compatibility: legacy rows have a 16-char `content_hash` while new rows will have 64. Update `ChangeDetector._classify` in `change_detector.py` to use a prefix-match helper:

```python
def _hash_matches(stored: str, fresh_full: str) -> bool:
    """Legacy rows stored 16-char prefix; new rows store 64-char full."""
    return fresh_full.startswith(stored) if len(stored) == 16 else fresh_full == stored
```

Replace the line `if content_hash_full(p) == rec.content_hash:` with `if _hash_matches(rec.content_hash, content_hash_full(p)):`.

- [ ] **Step 4: Run migration tests + detector tests (regression)**

Run:
```
wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_indexing_store_migration.py tests/unit/indexer/test_change_detector.py -v"
```
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/indexer/indexing_store.py src/piighost/indexer/change_detector.py tests/unit/test_indexing_store_migration.py
git commit -m "feat(indexer): backfill IndexingStore from legacy vault.indexed_files"
```

---

## Task 10: Service — rewrite index_path to incremental pipeline

**Files:**
- Modify: `src/piighost/service/core.py`
- Test: `tests/unit/test_service_incremental_v2.py`
- Regression: `tests/unit/test_service_incremental.py`, `tests/e2e/test_incremental_indexing.py`

**Context:** Replace the existing mtime-only loop with: detect → schedule → process new+modified → mark deleted → commit. Per-file try/except records `status='error'` and continues. Respect the `CancellationToken`. On entry, run `backfill_from_vault` exactly once per project (migration).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_service_incremental_v2.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    s = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield s
    asyncio.run(s.close())


def test_report_distinguishes_new_vs_modified(svc, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    a = folder / "a.txt"; a.write_text("Alice works in Paris")

    r1 = asyncio.run(svc.index_path(folder))
    assert r1.indexed == 1
    assert r1.modified == 0
    assert r1.unchanged == 0

    # Add a new file AND modify the existing one (bump mtime + content)
    a.write_text("Alice moved to Berlin")
    import os, time
    os.utime(a, (time.time(), time.time()))
    b = folder / "b.txt"; b.write_text("New doc")

    r2 = asyncio.run(svc.index_path(folder))
    assert r2.indexed == 1           # b.txt: new
    assert r2.modified == 1          # a.txt: content changed
    assert r2.unchanged == 0


def test_report_reports_deleted(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    a = folder / "a.txt"; a.write_text("hello")
    asyncio.run(svc.index_path(folder))
    a.unlink()
    r2 = asyncio.run(svc.index_path(folder))
    assert r2.deleted == 1
    assert r2.indexed == 0


def test_per_file_error_is_isolated(svc, tmp_path, monkeypatch):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "good.txt").write_text("Alice in Paris")
    bad = folder / "bad.txt"; bad.write_text("broken")

    # Monkeypatch extract_text to raise on bad.txt only
    from piighost.indexer import ingestor as ing
    real = ing.extract_text

    async def flaky(path, **kw):
        if path.name == "bad.txt":
            raise RuntimeError("simulated extraction failure")
        return await real(path, **kw)

    monkeypatch.setattr(ing, "extract_text", flaky)

    r = asyncio.run(svc.index_path(folder))
    assert r.indexed == 1
    assert len(r.errors) == 1
    assert "bad.txt" in r.errors[0]


def test_unchanged_still_skips_when_stat_matches(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "a.txt").write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder))
    r2 = asyncio.run(svc.index_path(folder))
    assert r2.unchanged == 1
    assert r2.indexed == 0
    assert r2.modified == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_service_incremental_v2.py -v"`
Expected: FAIL (e.g. `modified` field missing, or `deleted` not tracked).

- [ ] **Step 3: Rewrite index_path**

Edit `src/piighost/service/core.py`, replace the body of `_ProjectService.index_path` with:

```python
async def index_path(
    self, path: Path, *, recursive: bool = True, force: bool = False,
    cancel_token: "CancellationToken | None" = None,
) -> "IndexReport":
    import time as _time

    from piighost.indexer.chunker import chunk_text
    from piighost.indexer.identity import (
        content_hash, content_hash_full, file_fingerprint,
    )
    from piighost.indexer.ingestor import extract_text, list_document_paths
    from piighost.indexer.indexing_store import FileRecord, backfill_from_vault
    from piighost.indexer.change_detector import ChangeDetector
    from piighost.service.models import IndexReport

    # One-shot migration from legacy vault rows
    backfill_from_vault(self._indexing_store, self._vault, self._project_name)

    start = _time.monotonic()
    indexed = modified = deleted = skipped = unchanged = 0
    errors: list[str] = []

    if force:
        # full re-index — treat every file as new
        paths = await list_document_paths(path, recursive=recursive)
        targets = [(p.resolve(), "new") for p in paths]
        unchanged_paths: list[Path] = []
        deleted_paths: list[Path] = []
    else:
        detector = ChangeDetector(
            store=self._indexing_store, project_id=self._project_name
        )
        cs = await detector.scan_async(path, recursive=recursive)
        targets = (
            [(p, "new") for p in cs.new]
            + [(p, "modified") for p in cs.modified]
        )
        unchanged_paths = cs.unchanged
        deleted_paths = cs.deleted

    unchanged = len(unchanged_paths)

    with self._indexing_store.batch():
        # Handle deletions first
        for p in deleted_paths:
            self._indexing_store.mark_deleted(self._project_name, str(p))
            existing = self._vault.get_indexed_file_by_path(str(p))
            if existing is not None:
                self._chunk_store.delete_doc(existing.doc_id)
                self._vault.delete_doc_entities(existing.doc_id)
                self._vault.delete_indexed_file(existing.doc_id)
            deleted += 1

        # Process additions and modifications
        for p, kind in targets:
            if cancel_token is not None and cancel_token.is_cancelled:
                break
            try:
                stat_mtime, stat_size = file_fingerprint(p)
                text = await extract_text(p)
                if text is None:
                    skipped += 1
                    continue
                chash_full = content_hash_full(p)
                doc_id = chash_full[:16]

                # If replacing existing doc, clean up old vectors first
                existing = self._vault.get_indexed_file_by_path(str(p))
                if existing is not None:
                    self._chunk_store.delete_doc(existing.doc_id)
                    if existing.doc_id != doc_id:
                        self._vault.delete_doc_entities(existing.doc_id)
                        self._vault.delete_indexed_file(existing.doc_id)

                result = await self.anonymize(text, doc_id=doc_id)
                chunks = chunk_text(result.anonymized)
                if not chunks:
                    skipped += 1
                    continue

                vectors = await self._embedder.embed(chunks)
                self._chunk_store.upsert_chunks(doc_id, str(p), chunks, vectors)
                self._vault.upsert_indexed_file(
                    doc_id=doc_id, file_path=str(p),
                    content_hash=doc_id, mtime=stat_mtime,
                    chunk_count=len(chunks),
                )
                self._indexing_store.upsert(FileRecord(
                    project_id=self._project_name,
                    file_path=str(p),
                    file_mtime=stat_mtime,
                    file_size=stat_size,
                    content_hash=chash_full,
                    indexed_at=_time.time(),
                    status="success",
                    error_message=None,
                    entity_count=len(result.entities),
                    chunk_count=len(chunks),
                ))
                if kind == "modified":
                    modified += 1
                else:
                    indexed += 1
            except Exception as exc:  # noqa: BLE001 — per-file isolation
                err_msg = f"{type(exc).__name__}"
                errors.append(f"{p}: {err_msg}")
                try:
                    stat_mtime, stat_size = file_fingerprint(p)
                except OSError:
                    stat_mtime, stat_size = 0.0, 0
                self._indexing_store.upsert(FileRecord(
                    project_id=self._project_name,
                    file_path=str(p),
                    file_mtime=stat_mtime,
                    file_size=stat_size,
                    content_hash="",
                    indexed_at=_time.time(),
                    status="error",
                    error_message=err_msg,
                    entity_count=None,
                    chunk_count=None,
                ))

    if indexed > 0 or modified > 0 or deleted > 0 or errors:
        all_records = self._chunk_store.all_records()
        if all_records:
            self._bm25.rebuild(all_records)
        else:
            self._bm25.clear()

    duration_ms = int((_time.monotonic() - start) * 1000)
    return IndexReport(
        indexed=indexed,
        modified=modified,
        deleted=deleted,
        skipped=skipped,
        unchanged=unchanged,
        errors=errors,
        duration_ms=duration_ms,
    )
```

Update `PIIGhostService.index_path` to pass through a `cancel_token`:

```python
async def index_path(
    self, path: Path, *, recursive: bool = True, force: bool = False,
    project: str | None = None,
):
    from piighost.service.project_path import derive_project_from_path
    resolved = project if project is not None else derive_project_from_path(path)
    svc = await self._get_project(resolved, auto_create=True)
    cancel_token = self._cancel_registry.get_or_create(resolved)
    report = await svc.index_path(
        path, recursive=recursive, force=force, cancel_token=cancel_token,
    )
    # reset the token after the run so the next call starts fresh
    self._cancel_registry.reset(resolved)
    return report.model_copy(update={"project": resolved})
```

- [ ] **Step 4: Run the new and legacy tests**

Run:
```
wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_service_incremental_v2.py tests/unit/test_service_incremental.py tests/e2e/test_incremental_indexing.py -v"
```
Expected: all green. Existing tests read `unchanged` and `indexed` the same way; the new tests cover `modified` and `deleted`.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/service/core.py tests/unit/test_service_incremental_v2.py
git commit -m "feat(service): incremental indexer w/ modified+deleted tracking and per-file error isolation"
```

---

## Task 11: Service + MCP — check_folder_changes

**Files:**
- Modify: `src/piighost/service/core.py`
- Modify: `src/piighost/mcp/server.py`
- Test: `tests/unit/test_service_check_folder_changes.py`
- Test: `tests/unit/test_mcp_check_folder_changes.py`

**Context:** Spec §5. Read-only detector wrapper. Returns file paths + sizes by tier, plus total `unchanged_count`, plus the `BatchTier` so the caller (Claude) can decide whether to auto-index or ask the user.

- [ ] **Step 1: Write the failing test (service level)**

```python
# tests/unit/test_service_check_folder_changes.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    s = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield s
    asyncio.run(s.close())


def test_empty_folder_reports_empty_tier(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    r = asyncio.run(svc.check_folder_changes(str(folder)))
    assert r.tier == "empty"
    assert r.new == []
    assert r.modified == []
    assert r.deleted == []
    assert r.unchanged_count == 0


def test_two_new_files_report_small_tier(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "a.txt").write_text("hi")
    (folder / "b.txt").write_text("hello")
    r = asyncio.run(svc.check_folder_changes(str(folder)))
    assert r.tier == "small"
    assert {e.file_path for e in r.new} == {
        str(folder / "a.txt"), str(folder / "b.txt"),
    }


def test_after_index_folder_is_unchanged(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "a.txt").write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder))
    r = asyncio.run(svc.check_folder_changes(str(folder)))
    assert r.tier == "empty"
    assert r.unchanged_count == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_service_check_folder_changes.py -v"`
Expected: FAIL — `PIIGhostService` has no `check_folder_changes`.

- [ ] **Step 3: Implement service method**

Add to `_ProjectService` in `src/piighost/service/core.py`:

```python
async def check_folder_changes(
    self, folder: Path, *, recursive: bool = True
) -> "FolderChangesResult":
    from piighost.indexer.change_detector import ChangeDetector
    from piighost.indexer.batch_scheduler import classify_batch
    from piighost.service.models import FolderChangesResult, FileChangeEntry
    from piighost.indexer.indexing_store import backfill_from_vault

    backfill_from_vault(self._indexing_store, self._vault, self._project_name)
    det = ChangeDetector(store=self._indexing_store, project_id=self._project_name)
    cs = await det.scan_async(folder, recursive=recursive)
    tier = classify_batch(cs, self._config.incremental)

    def _entry(p: Path) -> FileChangeEntry:
        try:
            return FileChangeEntry(file_path=str(p), size=p.stat().st_size)
        except OSError:
            return FileChangeEntry(file_path=str(p), size=0)

    return FolderChangesResult(
        folder=str(folder),
        project=self._project_name,
        new=[_entry(p) for p in cs.new],
        modified=[_entry(p) for p in cs.modified],
        deleted=[str(p) for p in cs.deleted],
        unchanged_count=len(cs.unchanged),
        tier=tier.value,
    )
```

And on `PIIGhostService`:

```python
async def check_folder_changes(
    self, folder: str, *, recursive: bool = True, project: str | None = None,
):
    from piighost.service.project_path import derive_project_from_path
    folder_path = Path(folder).expanduser().resolve()
    resolved = project if project is not None else derive_project_from_path(folder_path)
    svc = await self._get_project(resolved, auto_create=True)
    return await svc.check_folder_changes(folder_path, recursive=recursive)
```

- [ ] **Step 4: Write the MCP-wiring failing test**

```python
# tests/unit/test_mcp_check_folder_changes.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.mcp.server import build_mcp


@pytest.fixture()
def mcp_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    mcp, svc = asyncio.run(build_mcp(tmp_path / "vault"))
    yield mcp, svc
    asyncio.run(svc.close())


def test_check_folder_changes_tool_is_registered(mcp_pair):
    mcp, _ = mcp_pair
    tools = asyncio.run(mcp.get_tools())
    assert "check_folder_changes" in {t.name for t in tools}


def test_check_folder_changes_returns_payload(mcp_pair, tmp_path):
    mcp, _ = mcp_pair
    folder = tmp_path / "f"; folder.mkdir()
    (folder / "a.txt").write_text("x")
    tools = asyncio.run(mcp.get_tools())
    tool = next(t for t in tools if t.name == "check_folder_changes")
    result = asyncio.run(tool.fn(folder=str(folder)))
    assert result["tier"] == "small"
    assert len(result["new"]) == 1
```

(Adjust `mcp.get_tools()` / `tool.fn` to match how `test_mcp_server.py` currently introspects tools — reuse its patterns.)

- [ ] **Step 5: Run to verify failure**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_mcp_check_folder_changes.py -v"`
Expected: FAIL — tool not registered.

- [ ] **Step 6: Register MCP tool**

In `src/piighost/mcp/server.py`, inside the `_indexing_available()` branch, after `query`:

```python
@mcp.tool(
    description=(
        "Scan a folder and return which files are new / modified / "
        "deleted / unchanged, plus a tier hint (small/medium/large) "
        "so the caller can decide whether to auto-index or ask the user."
    )
)
async def check_folder_changes(
    folder: str, recursive: bool = True, project: str = ""
) -> dict:
    project_arg = project if project else None
    result = await svc.check_folder_changes(
        folder, recursive=recursive, project=project_arg
    )
    return result.model_dump()
```

- [ ] **Step 7: Run tests**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_service_check_folder_changes.py tests/unit/test_mcp_check_folder_changes.py -v"`
Expected: all passing.

- [ ] **Step 8: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/service/core.py src/piighost/mcp/server.py tests/unit/test_service_check_folder_changes.py tests/unit/test_mcp_check_folder_changes.py
git commit -m "feat(mcp): check_folder_changes tool + service API"
```

---

## Task 12: Service + MCP — cancel_indexing

**Files:**
- Modify: `src/piighost/service/core.py`
- Modify: `src/piighost/mcp/server.py`
- Test: `tests/unit/test_service_cancel_indexing.py`
- Test: `tests/unit/test_mcp_cancel_indexing.py`

**Context:** Spec §5. `cancel_indexing(project)` flips the token on the registry; the next between-files check in `_ProjectService.index_path` breaks out of the loop. Because tests run synchronously, simulate cancellation by flipping the token via a hook before a multi-file run.

- [ ] **Step 1: Write the failing test (service)**

```python
# tests/unit/test_service_cancel_indexing.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    s = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield s
    asyncio.run(s.close())


def test_cancel_stops_loop_between_files(svc, tmp_path, monkeypatch):
    folder = tmp_path / "docs"; folder.mkdir()
    for i in range(5):
        (folder / f"f{i}.txt").write_text(f"file {i}")

    # Monkeypatch extract_text to cancel after first file completes
    from piighost.indexer import ingestor as ing
    real = ing.extract_text
    seen = {"n": 0}

    async def counting(path, **kw):
        seen["n"] += 1
        if seen["n"] == 2:
            # Trigger cancel after second file starts
            result = await svc.cancel_indexing(project="default")
            assert result.cancelled is True
        return await real(path, **kw)

    monkeypatch.setattr(ing, "extract_text", counting)
    r = asyncio.run(svc.index_path(folder, project="default"))
    # At least one file indexed, but not all 5 (cancel broke the loop)
    assert r.indexed + r.modified < 5


def test_cancel_nonexistent_project_is_noop(svc):
    r = asyncio.run(svc.cancel_indexing(project="no-such"))
    # We still return a CancelResult even when nothing was running
    assert r.cancelled is True
    assert r.project == "no-such"
```

- [ ] **Step 2: Run to verify failure**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_service_cancel_indexing.py -v"`
Expected: FAIL — `cancel_indexing` not defined.

- [ ] **Step 3: Add service API**

In `PIIGhostService` (`src/piighost/service/core.py`):

```python
async def cancel_indexing(self, *, project: str = "default"):
    from piighost.service.models import CancelResult
    token = self._cancel_registry.get_or_create(project)
    token.cancel()
    return CancelResult(project=project, cancelled=True)
```

- [ ] **Step 4: Write the MCP wiring test**

```python
# tests/unit/test_mcp_cancel_indexing.py
import asyncio
import pytest
from piighost.mcp.server import build_mcp


@pytest.fixture()
def mcp_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    mcp, svc = asyncio.run(build_mcp(tmp_path / "vault"))
    yield mcp, svc
    asyncio.run(svc.close())


def test_cancel_indexing_tool_registered(mcp_pair):
    mcp, _ = mcp_pair
    tools = asyncio.run(mcp.get_tools())
    assert "cancel_indexing" in {t.name for t in tools}


def test_cancel_indexing_returns_result(mcp_pair):
    mcp, _ = mcp_pair
    tools = asyncio.run(mcp.get_tools())
    tool = next(t for t in tools if t.name == "cancel_indexing")
    result = asyncio.run(tool.fn(project="default"))
    assert result["cancelled"] is True
```

- [ ] **Step 5: Run to verify failure**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_mcp_cancel_indexing.py -v"`
Expected: FAIL — tool not registered.

- [ ] **Step 6: Register MCP tool**

In `src/piighost/mcp/server.py` (inside `_indexing_available()` block):

```python
@mcp.tool(
    description=(
        "Signal a running index_path() to stop after the current file. "
        "The currently-processing file completes; remaining files are "
        "skipped. Safe to call even when no index is running."
    )
)
async def cancel_indexing(project: str = "default") -> dict:
    result = await svc.cancel_indexing(project=project)
    return result.model_dump()
```

- [ ] **Step 7: Run tests**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_service_cancel_indexing.py tests/unit/test_mcp_cancel_indexing.py -v"`
Expected: all passing.

- [ ] **Step 8: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add src/piighost/service/core.py src/piighost/mcp/server.py tests/unit/test_service_cancel_indexing.py tests/unit/test_mcp_cancel_indexing.py
git commit -m "feat(mcp): cancel_indexing tool + CancellationToken integration"
```

---

## Task 13: E2E scenarios from spec

**Files:**
- Create: `tests/e2e/test_incremental_indexing_v2.py`

**Context:** Spec §Testing / Integration + E2E. Cover: add-then-add (only new processed), modify file (re-indexed with entity count refreshed), delete file (reported), multi-project isolation, corrupted file isolation, forced full re-index regression.

- [ ] **Step 1: Write the test file**

```python
# tests/e2e/test_incremental_indexing_v2.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    s = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield s
    asyncio.run(s.close())


def test_add_files_in_two_waves(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    for i in range(5):
        (folder / f"a{i}.txt").write_text(f"Alice in Paris {i}")
    r1 = asyncio.run(svc.index_path(folder, project="proj"))
    assert r1.indexed == 5

    for i in range(3):
        (folder / f"b{i}.txt").write_text(f"Bob in Berlin {i}")
    r2 = asyncio.run(svc.index_path(folder, project="proj"))
    assert r2.indexed == 3
    assert r2.unchanged == 5


def test_modify_file_triggers_reindex(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    f = folder / "c.txt"; f.write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder, project="proj"))

    # truly change the content, not just mtime
    import os, time
    f.write_text("Alice in Berlin, completely different content now.")
    os.utime(f, (time.time() + 10, time.time() + 10))
    r = asyncio.run(svc.index_path(folder, project="proj"))
    assert r.modified == 1


def test_delete_is_reported(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    f = folder / "d.txt"; f.write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder, project="proj"))
    f.unlink()
    r = asyncio.run(svc.index_path(folder, project="proj"))
    assert r.deleted == 1


def test_check_folder_changes_sees_deletion(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    f = folder / "d.txt"; f.write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder, project="proj"))
    f.unlink()
    changes = asyncio.run(svc.check_folder_changes(str(folder), project="proj"))
    assert changes.deleted == [str(f.resolve())]


def test_multi_project_isolation(svc, tmp_path):
    a = tmp_path / "A"; a.mkdir()
    b = tmp_path / "B"; b.mkdir()
    (a / "x.txt").write_text("Alice in Paris")
    asyncio.run(svc.index_path(a, project="A"))

    # Project B has no entries — check_folder_changes on B sees only new
    (b / "y.txt").write_text("Bob in Berlin")
    r_b = asyncio.run(svc.check_folder_changes(str(b), project="B"))
    assert len(r_b.new) == 1
    # A is still fully indexed
    r_a = asyncio.run(svc.check_folder_changes(str(a), project="A"))
    assert r_a.unchanged_count == 1


def test_corrupted_file_does_not_break_batch(svc, tmp_path, monkeypatch):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "good.txt").write_text("Alice in Paris")
    (folder / "bad.pdf").write_bytes(b"NOT-A-PDF")
    r = asyncio.run(svc.index_path(folder, project="proj"))
    # good file succeeds even if bad one fails
    assert r.indexed >= 1


def test_force_true_preserves_old_behavior(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "a.txt").write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder, project="proj"))
    r = asyncio.run(svc.index_path(folder, project="proj", force=True))
    assert r.indexed == 1
    assert r.unchanged == 0
    assert r.modified == 0
```

- [ ] **Step 2: Run**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/e2e/test_incremental_indexing_v2.py -v"`
Expected: 7 passing.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add tests/e2e/test_incremental_indexing_v2.py
git commit -m "test(e2e): incremental indexing v2 scenarios (waves, modify, delete, isolation)"
```

---

## Task 14: Performance test

**Files:**
- Create: `tests/e2e/test_incremental_indexing_perf.py`

**Context:** Spec §Performance. Two targets:
- 1,000-file folder, zero changes → detection under 500ms
- 1,000 files, 10 new → new-work time is a small fraction of the full-index time

The stub embedder + stub detector keep per-file cost minimal, so wall-clock times are small but the *ratio* stays meaningful. Gate the tests with `pytest.mark.slow` so they only run in CI.

- [ ] **Step 1: Write the test**

```python
# tests/e2e/test_incremental_indexing_perf.py
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


pytestmark = pytest.mark.slow


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    s = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield s
    asyncio.run(s.close())


def _seed(folder: Path, n: int) -> None:
    folder.mkdir(exist_ok=True)
    for i in range(n):
        (folder / f"f{i}.txt").write_text(f"Alice works in Paris row {i}")


def test_detection_under_500ms_with_1000_unchanged_files(svc, tmp_path):
    folder = tmp_path / "f"
    _seed(folder, 1000)
    asyncio.run(svc.index_path(folder, project="p"))
    t0 = time.monotonic()
    r = asyncio.run(svc.check_folder_changes(str(folder), project="p"))
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert r.unchanged_count == 1000
    assert r.tier == "empty"
    assert elapsed_ms < 500, f"detection took {elapsed_ms:.0f}ms"


def test_incremental_is_faster_than_full_reindex(svc, tmp_path):
    folder = tmp_path / "f"
    _seed(folder, 1000)
    t_full = time.monotonic()
    asyncio.run(svc.index_path(folder, project="p"))
    t_full = time.monotonic() - t_full

    # Add 10 new files, then re-index incrementally
    for i in range(1000, 1010):
        (folder / f"f{i}.txt").write_text(f"Bob row {i}")

    t_inc = time.monotonic()
    r = asyncio.run(svc.index_path(folder, project="p"))
    t_inc = time.monotonic() - t_inc

    assert r.indexed == 10
    assert r.unchanged == 1000
    # Incremental (10 files) should be well under 1/3 of full (1000 files)
    assert t_inc < t_full / 3, f"incremental {t_inc:.2f}s not << full {t_full:.2f}s"
```

Add `slow` marker to `pyproject.toml` under `[tool.pytest.ini_options]` if not already present:

```toml
[tool.pytest.ini_options]
markers = [
    "slow: marks tests that take more than a few seconds",
]
```

- [ ] **Step 2: Run the perf tests explicitly**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/e2e/test_incremental_indexing_perf.py -v -m slow"`
Expected: 2 passing. If perf margins fail, investigate before loosening the thresholds.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add tests/e2e/test_incremental_indexing_perf.py pyproject.toml
git commit -m "test(perf): incremental indexing detection + speedup targets"
```

---

## Task 15: Full regression + CI run

**Files:** none (verification only).

**Context:** Final gate before shipping. Run the complete test matrix and verify nothing regressed. Explicitly check the legacy test files this plan touches behavior for.

- [ ] **Step 1: Run the full unit + e2e suite under WSL**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/ -x -q"`
Expected: all green. Any failures must be fixed before moving on.

- [ ] **Step 2: Run the targeted regression slice**

Run:
```
wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && pytest tests/unit/test_service_incremental.py tests/unit/test_service_incremental_v2.py tests/unit/test_service_index.py tests/unit/test_service_index_status.py tests/unit/test_service_remove_doc.py tests/unit/test_vault_indexed_files.py tests/e2e/test_incremental_indexing.py tests/e2e/test_incremental_indexing_v2.py tests/unit/test_mcp_server.py tests/unit/test_mcp_indexing_gate.py -v"`
```
Expected: all green.

- [ ] **Step 3: Lint + format sanity**

Run: `wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && python -m ruff check src/ tests/ 2>&1 | head -50"` (or whichever linter the project uses — check `pyproject.toml`).
Expected: no new warnings in files this plan touched.

- [ ] **Step 4: Commit any lint fixes**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git status
# only if there are changes:
git add -u && git commit -m "chore: lint cleanup for incremental indexing"
```

---

## Notes for the implementer

- **Run tests in WSL, not Windows.** Every command above prefixes `wsl bash -c "cd /mnt/c/..."`. The project's `CLAUDE.md` (in the Rust sibling repo) documents why; piighost has similar behavior with ONNX / HF dependencies when using real models.
- **Use the stub embedder + stub detector** for every unit and most e2e tests. `PIIGHOST_EMBEDDER=stub`, `PIIGHOST_DETECTOR=stub`. Real gliner2 / multilingual-e5 require GPU-grade wait times and are exercised manually by the mixed-corpus test script under `C:\tmp\hacienda-demo\`.
- **DRY:** the scan/detect/classify pipeline is orchestrated only inside `_ProjectService` — neither the MCP layer nor the CLI duplicates it. Both call `check_folder_changes` / `index_path`.
- **YAGNI:** do NOT add background watchers, CLI flags for per-tier overrides, or automatic LanceDB cleanup for deleted files in this PR. The spec explicitly defers those.
- **Frequent commits:** one commit per task, message format `feat|fix|refactor|test(scope): message`. Don't squash — reviewers use per-task diffs.
- **Preserve `force=True` behavior exactly.** The existing e2e test `test_force_flag_reindexes_all` is a guardrail — never modify it.
- **LanceDB write failures** — per spec §Error Handling Reference, they land in the per-file try/except branch and are recorded as `status='error'` without killing the batch. Task 10's code path already covers this because it wraps `upsert_chunks` inside the per-file try.

## Deferred to follow-up plans (explicitly out of scope here)

These items from the design spec are intentionally NOT implemented in this plan. Each has a clear boundary that lets us ship value sooner and revisit once the core pipeline is in production:

1. **Query-time transparent freshness** (spec §5, "`query()` will trigger a silent `check_folder_changes`…") — requires the service to remember each project's indexed folder, plus a session-level gate to avoid re-scanning on every query. Deferred: the MCP client (Claude) can call `check_folder_changes` + `index_path` explicitly before `query` to get the same effect in v1.
2. **Session-scoped "ask once per session" state for the medium tier** — the scheduler returns the tier; the client decides what to do with it. Daemon-level session tracking can come later if the CLI wants it.
3. **Automatic LanceDB chunk cleanup for files marked `status='deleted'`** — spec §Non-Goals confirms this is deferred.
4. **`schema_version` future migrations beyond v1** — the column exists and is stamped; adding migration code (v1→v2) is a new plan when we need it.
