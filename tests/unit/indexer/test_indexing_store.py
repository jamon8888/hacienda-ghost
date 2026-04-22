import sqlite3
from pathlib import Path
import pytest

from piighost.indexer.indexing_store import IndexingStore, FileRecord


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
        store.upsert(FileRecord(
            project_id="proj", file_path="/abs/a.txt",
            file_mtime=1.0, file_size=99, content_hash="y" * 64,
            indexed_at=1.0, status="success",
            error_message=None, entity_count=0, chunk_count=0,
        ))
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
