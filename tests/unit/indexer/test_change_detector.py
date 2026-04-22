# tests/unit/indexer/test_change_detector.py
from __future__ import annotations

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
