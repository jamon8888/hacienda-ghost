from __future__ import annotations

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
