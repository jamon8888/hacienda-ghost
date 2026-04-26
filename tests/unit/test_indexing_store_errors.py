"""Tests for IndexingStore.list_errors and count_errors."""
from __future__ import annotations

import pytest

from piighost.indexer.indexing_store import FileRecord, IndexingStore


def _record(
    *, project: str, path: str, status: str, indexed_at: float,
    error_message: str | None = None,
) -> FileRecord:
    return FileRecord(
        project_id=project,
        file_path=path,
        file_mtime=0.0,
        file_size=0,
        content_hash="",
        indexed_at=indexed_at,
        status=status,
        error_message=error_message,
        entity_count=None,
        chunk_count=None,
    )


@pytest.fixture()
def store(tmp_path):
    s = IndexingStore.open(tmp_path / "indexing.sqlite")
    yield s
    s.close()


def test_list_errors_returns_only_error_status(store):
    store.upsert(_record(project="p", path="/a.pdf", status="success",
                         indexed_at=100.0))
    store.upsert(_record(project="p", path="/b.pdf", status="error",
                         indexed_at=101.0,
                         error_message="ExtractionError: corrupt"))
    store.upsert(_record(project="p", path="/c.pdf", status="deleted",
                         indexed_at=102.0))

    errs = store.list_errors("p")
    assert len(errs) == 1
    assert errs[0].file_path == "/b.pdf"
    assert errs[0].status == "error"
    assert errs[0].error_message == "ExtractionError: corrupt"


def test_list_errors_orders_by_indexed_at_desc(store):
    store.upsert(_record(project="p", path="/old.pdf", status="error",
                         indexed_at=100.0,
                         error_message="ExtractionError: corrupt"))
    store.upsert(_record(project="p", path="/new.pdf", status="error",
                         indexed_at=200.0,
                         error_message="ExtractionError: corrupt"))
    store.upsert(_record(project="p", path="/mid.pdf", status="error",
                         indexed_at=150.0,
                         error_message="ExtractionError: corrupt"))

    errs = store.list_errors("p")
    assert [r.file_path for r in errs] == ["/new.pdf", "/mid.pdf", "/old.pdf"]


def test_list_errors_honours_limit_and_count_returns_total(store):
    for i in range(60):
        store.upsert(_record(
            project="p", path=f"/f{i}.pdf", status="error",
            indexed_at=float(i),
            error_message="ExtractionError: corrupt",
        ))

    errs = store.list_errors("p", limit=50)
    assert len(errs) == 50
    # Newest first → /f59.pdf is the first row
    assert errs[0].file_path == "/f59.pdf"
    assert store.count_errors("p") == 60


def test_list_errors_isolates_by_project(store):
    store.upsert(_record(project="p", path="/a.pdf", status="error",
                         indexed_at=100.0,
                         error_message="ExtractionError: corrupt"))
    store.upsert(_record(project="q", path="/a.pdf", status="error",
                         indexed_at=101.0,
                         error_message="ExtractionError: corrupt"))

    assert len(store.list_errors("p")) == 1
    assert len(store.list_errors("q")) == 1
    assert store.count_errors("p") == 1
    assert store.count_errors("q") == 1


def test_count_errors_returns_zero_for_unknown_project(store):
    assert store.count_errors("does-not-exist") == 0
    assert store.list_errors("does-not-exist") == []
