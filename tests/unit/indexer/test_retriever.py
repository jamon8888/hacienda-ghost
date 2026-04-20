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
    assert "c1" in chunk_ids


def test_bm25_search_no_match(tmp_path):
    idx = BM25Index(tmp_path / "bm25.pkl")
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
    ids = [cid for cid, _ in result]
    assert "c1" in ids and "c2" in ids


def test_rrf_empty_inputs():
    assert reciprocal_rank_fusion([], []) == []
