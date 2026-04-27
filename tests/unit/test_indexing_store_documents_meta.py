"""Tests for IndexingStore.upsert_document_meta + get/list/documents_meta_for/delete."""
from __future__ import annotations

import pytest

from piighost.indexer.indexing_store import IndexingStore
from piighost.service.models import DocumentMetadata


def _meta(
    *, doc_id: str, doc_type: str = "contrat", doc_date: int | None = 1777200000,
    title: str | None = "Test Doc", parties: list[str] | None = None,
    dossier_id: str = "client1",
) -> DocumentMetadata:
    return DocumentMetadata(
        doc_id=doc_id,
        doc_type=doc_type,
        doc_type_confidence=0.9,
        doc_date=doc_date,
        doc_date_source="kreuzberg_creation" if doc_date else "none",
        doc_title=title,
        doc_authors=["Jean Martin"],
        doc_language="fr",
        doc_page_count=3,
        doc_format="pdf",
        parties=parties or ["<<nom_personne:abc>>"],
        dossier_id=dossier_id,
        extracted_at=1777200000,
    )


@pytest.fixture()
def store(tmp_path):
    s = IndexingStore.open(tmp_path / "indexing.sqlite")
    yield s
    s.close()


def test_upsert_and_get_document_meta(store):
    store.upsert_document_meta("p1", _meta(doc_id="abc"))
    got = store.get_document_meta("p1", "abc")
    assert got is not None
    assert got.doc_id == "abc"
    assert got.doc_type == "contrat"
    assert got.parties == ["<<nom_personne:abc>>"]


def test_get_document_meta_missing_returns_none(store):
    assert store.get_document_meta("p1", "missing") is None


def test_upsert_document_meta_replaces_existing(store):
    store.upsert_document_meta("p1", _meta(doc_id="abc", doc_type="contrat"))
    store.upsert_document_meta("p1", _meta(doc_id="abc", doc_type="facture"))
    got = store.get_document_meta("p1", "abc")
    assert got.doc_type == "facture"


def test_documents_meta_for_doc_ids(store):
    for i in range(3):
        store.upsert_document_meta("p1", _meta(doc_id=f"d{i}"))
    out = store.documents_meta_for("p1", ["d0", "d2"])
    ids = sorted(m.doc_id for m in out)
    assert ids == ["d0", "d2"]


def test_documents_meta_for_empty_list_returns_empty(store):
    assert store.documents_meta_for("p1", []) == []


def test_documents_meta_isolated_by_project(store):
    store.upsert_document_meta("p1", _meta(doc_id="abc"))
    store.upsert_document_meta("p2", _meta(doc_id="abc"))
    assert store.get_document_meta("p1", "abc") is not None
    assert store.get_document_meta("p2", "abc") is not None
    p1_only = store.documents_meta_for("p1", ["abc"])
    assert len(p1_only) == 1


def test_list_documents_meta_by_dossier(store):
    store.upsert_document_meta("p1", _meta(doc_id="d1", dossier_id="client1"))
    store.upsert_document_meta("p1", _meta(doc_id="d2", dossier_id="client2"))
    store.upsert_document_meta("p1", _meta(doc_id="d3", dossier_id="client1"))
    c1 = store.list_documents_meta("p1", dossier_id="client1")
    assert sorted(m.doc_id for m in c1) == ["d1", "d3"]


def test_list_documents_meta_by_doc_type(store):
    store.upsert_document_meta("p1", _meta(doc_id="d1", doc_type="contrat"))
    store.upsert_document_meta("p1", _meta(doc_id="d2", doc_type="facture"))
    store.upsert_document_meta("p1", _meta(doc_id="d3", doc_type="contrat"))
    contracts = store.list_documents_meta("p1", doc_type="contrat")
    assert sorted(m.doc_id for m in contracts) == ["d1", "d3"]


def test_delete_document_meta(store):
    store.upsert_document_meta("p1", _meta(doc_id="abc"))
    assert store.get_document_meta("p1", "abc") is not None
    store.delete_document_meta("p1", "abc")
    assert store.get_document_meta("p1", "abc") is None


def test_round_trip_preserves_all_fields(store):
    """Ensure JSON serialization for parties/authors round-trips correctly."""
    meta = DocumentMetadata(
        doc_id="full",
        doc_type="email",
        doc_type_confidence=0.78,
        doc_date=1700000000,
        doc_date_source="heuristic_detected",
        doc_title="Subject Line",
        doc_subject="OG subject",
        doc_authors=["Alice", "Bob", "Céline"],
        doc_language="fr",
        doc_page_count=None,
        doc_format="eml",
        is_encrypted_source=True,
        parties=["<<email:abc>>", "<<nom_personne:def>>"],
        dossier_id="dossier-x",
        extracted_at=1700000001,
    )
    store.upsert_document_meta("p1", meta)
    got = store.get_document_meta("p1", "full")
    assert got is not None
    # Compare via model_dump for full equality
    assert got.model_dump() == meta.model_dump()
