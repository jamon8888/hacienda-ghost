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
