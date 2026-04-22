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
