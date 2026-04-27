"""Tests for ChunkStore.chunks_for_doc_ids + update_chunks (Phase 1).

Both _meta_mode (stub embedder) and LanceDB mode must work.
"""
from __future__ import annotations

import pytest

from piighost.indexer.store import ChunkStore


@pytest.fixture()
def store(tmp_path):
    s = ChunkStore(tmp_path / "lance")
    yield s


def test_chunks_for_doc_ids_returns_only_requested_meta_mode(store):
    """In _meta_mode (no vectors), the in-memory list is filtered by doc_id."""
    # Empty vectors → triggers meta_mode
    store.upsert_chunks("d1", "/a.pdf",
                       texts=["chunk a1", "chunk a2"], vectors=[[], []])
    store.upsert_chunks("d2", "/b.pdf",
                       texts=["chunk b1"], vectors=[[]])
    store.upsert_chunks("d3", "/c.pdf",
                       texts=["chunk c1"], vectors=[[]])
    out = store.chunks_for_doc_ids(["d1", "d3"])
    doc_ids = sorted({r["doc_id"] for r in out})
    assert doc_ids == ["d1", "d3"]
    assert len(out) == 3  # 2 from d1 + 1 from d3


def test_chunks_for_doc_ids_empty_input_returns_empty(store):
    store.upsert_chunks("d1", "/a.pdf", texts=["x"], vectors=[[]])
    assert store.chunks_for_doc_ids([]) == []


def test_chunks_for_doc_ids_unknown_doc_returns_empty(store):
    store.upsert_chunks("d1", "/a.pdf", texts=["x"], vectors=[[]])
    assert store.chunks_for_doc_ids(["unknown"]) == []


def test_update_chunks_replaces_text_meta_mode(store):
    """Update by chunk_id, replacing text + vector in-place."""
    store.upsert_chunks("d1", "/a.pdf",
                       texts=["original text"], vectors=[[]])
    rows = store.chunks_for_doc_ids(["d1"])
    assert len(rows) == 1
    target = rows[0]
    store.update_chunks([(target, "rewritten text", [])])
    after = store.chunks_for_doc_ids(["d1"])
    assert len(after) == 1
    assert after[0]["chunk"] == "rewritten text"
    assert after[0]["doc_id"] == "d1"
    assert after[0]["chunk_id"] == target["chunk_id"]


def test_update_chunks_preserves_unaffected_chunks(store):
    """Rewriting one chunk leaves others untouched."""
    store.upsert_chunks("d1", "/a.pdf",
                       texts=["A", "B", "C"], vectors=[[], [], []])
    rows = store.chunks_for_doc_ids(["d1"])
    middle = next(r for r in rows if r["chunk"] == "B")
    store.update_chunks([(middle, "B-rewritten", [])])
    after = sorted(store.chunks_for_doc_ids(["d1"]),
                   key=lambda r: r.get("chunk_id", ""))
    texts = [r["chunk"] for r in after]
    assert "A" in texts
    assert "B-rewritten" in texts
    assert "C" in texts
    # B (original) is gone
    assert "B" not in texts


def test_update_chunks_empty_input_is_noop(store):
    """Empty updates list should not raise."""
    store.upsert_chunks("d1", "/a.pdf", texts=["x"], vectors=[[]])
    store.update_chunks([])  # no-op
    rows = store.chunks_for_doc_ids(["d1"])
    assert len(rows) == 1
    assert rows[0]["chunk"] == "x"


def test_update_chunks_handles_multi_doc_batch(store):
    """A single update_chunks call can rewrite chunks from multiple docs."""
    store.upsert_chunks("d1", "/a.pdf", texts=["doc1 text"], vectors=[[]])
    store.upsert_chunks("d2", "/b.pdf", texts=["doc2 text"], vectors=[[]])
    rows = store.chunks_for_doc_ids(["d1", "d2"])
    updates = [(r, r["chunk"] + " updated", []) for r in rows]
    store.update_chunks(updates)
    after = store.chunks_for_doc_ids(["d1", "d2"])
    texts = sorted(r["chunk"] for r in after)
    assert texts == ["doc1 text updated", "doc2 text updated"]
