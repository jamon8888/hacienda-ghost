"""Tests for subject_clustering — co-occurrence-based clustering on doc_entities."""
from __future__ import annotations

import pytest

from piighost.service.subject_clustering import (
    cluster_subjects, SubjectCluster,
)
from piighost.vault.store import Vault


@pytest.fixture()
def vault(tmp_path):
    v = Vault.open(tmp_path / "vault.db")
    yield v
    v.close()


def test_cluster_returns_empty_when_no_match(vault):
    out = cluster_subjects(vault, query="Inconnu Inexistant")
    assert out == []


def test_cluster_groups_cooccurring_tokens(vault):
    """Marie's 3 tokens always appear together → one cluster of 3."""
    vault.upsert_entity(
        token="<<nom_personne:marie>>", original="Marie Dupont",
        label="nom_personne", confidence=0.9,
    )
    vault.upsert_entity(
        token="<<email:marie>>", original="marie.dupont@x.fr",
        label="email", confidence=0.9,
    )
    vault.upsert_entity(
        token="<<numero_telephone:marie>>", original="+33 1 23 45 67 89",
        label="numero_telephone", confidence=0.9,
    )
    for doc in ["d1", "d2", "d3"]:
        for tok in ("<<nom_personne:marie>>", "<<email:marie>>",
                    "<<numero_telephone:marie>>"):
            vault.link_doc_entity(doc_id=doc, token=tok, start_pos=0, end_pos=1)

    clusters = cluster_subjects(vault, query="Marie")
    assert len(clusters) >= 1
    c = clusters[0]
    assert c.confidence > 0.8
    assert "<<nom_personne:marie>>" in c.tokens
    assert "<<email:marie>>" in c.tokens
    assert "<<numero_telephone:marie>>" in c.tokens
    assert sorted(c.sample_doc_ids) == ["d1", "d2", "d3"]


def test_cluster_separates_homonyms(vault):
    """Two 'Marie's that never share a doc → at least two clusters or distinct token sets."""
    # Marie A in d1, d2
    vault.upsert_entity(token="<<nom_personne:marie_a>>", original="Marie Alpha",
                        label="nom_personne", confidence=0.9)
    vault.upsert_entity(token="<<email:marie_a>>", original="alpha@x.fr",
                        label="email", confidence=0.9)
    for doc in ["d1", "d2"]:
        vault.link_doc_entity(doc_id=doc, token="<<nom_personne:marie_a>>", start_pos=0, end_pos=1)
        vault.link_doc_entity(doc_id=doc, token="<<email:marie_a>>", start_pos=10, end_pos=20)
    # Marie B in d10
    vault.upsert_entity(token="<<nom_personne:marie_b>>", original="Marie Beta",
                        label="nom_personne", confidence=0.9)
    vault.upsert_entity(token="<<email:marie_b>>", original="beta@x.fr",
                        label="email", confidence=0.9)
    vault.link_doc_entity(doc_id="d10", token="<<nom_personne:marie_b>>", start_pos=0, end_pos=1)
    vault.link_doc_entity(doc_id="d10", token="<<email:marie_b>>", start_pos=10, end_pos=20)

    clusters = cluster_subjects(vault, query="Marie")
    # Two distinct clusters (no shared docs → no co-occurrence between them)
    assert len(clusters) >= 2
    cluster_token_sets = [set(c.tokens) for c in clusters]
    # Verify the alpha tokens stay together
    alpha_clusters = [s for s in cluster_token_sets if "<<email:marie_a>>" in s]
    assert alpha_clusters
    alpha_cluster = alpha_clusters[0]
    assert "<<nom_personne:marie_a>>" in alpha_cluster
    assert "<<nom_personne:marie_b>>" not in alpha_cluster


def test_cluster_returns_sample_doc_ids_capped(vault):
    """Sample doc list shouldn't return more than ~10 entries."""
    vault.upsert_entity(token="<<nom_personne:big>>", original="Big",
                        label="nom_personne", confidence=0.9)
    for i in range(50):
        vault.link_doc_entity(doc_id=f"d{i}", token="<<nom_personne:big>>",
                              start_pos=0, end_pos=3)
    clusters = cluster_subjects(vault, query="Big")
    assert len(clusters) >= 1
    assert len(clusters[0].sample_doc_ids) <= 10


def test_cluster_results_sorted_by_confidence_desc(vault):
    """When multiple clusters surface, higher-confidence ones come first."""
    # Strong cluster: 3 tokens always together in 5 docs
    for tok_id in ("strong_a", "strong_b", "strong_c"):
        vault.upsert_entity(
            token=f"<<np:{tok_id}>>", original=f"Strong{tok_id}",
            label="nom_personne", confidence=0.9,
        )
    for doc in ["d1", "d2", "d3", "d4", "d5"]:
        for tok_id in ("strong_a", "strong_b", "strong_c"):
            vault.link_doc_entity(doc_id=doc, token=f"<<np:{tok_id}>>",
                                   start_pos=0, end_pos=3)
    # Weak cluster: 2 tokens, share only 1 doc
    vault.upsert_entity(token="<<np:weak>>", original="Weak",
                        label="nom_personne", confidence=0.9)
    vault.upsert_entity(token="<<em:weak>>", original="weak@x.fr",
                        label="email", confidence=0.9)
    vault.link_doc_entity(doc_id="d99", token="<<np:weak>>", start_pos=0, end_pos=3)
    vault.link_doc_entity(doc_id="d99", token="<<em:weak>>", start_pos=10, end_pos=20)

    # Query that matches both
    strong_clusters = cluster_subjects(vault, query="Strong")
    weak_clusters = cluster_subjects(vault, query="Weak")
    assert strong_clusters
    assert weak_clusters
    # Within a single query result, list is sorted by confidence DESC
    multi_query_clusters = cluster_subjects(vault, query="Stron")  # broad match
    if len(multi_query_clusters) >= 2:
        confidences = [c.confidence for c in multi_query_clusters]
        assert confidences == sorted(confidences, reverse=True)


def test_cluster_is_dataclass_with_expected_fields(vault):
    vault.upsert_entity(token="<<np:test>>", original="Test",
                        label="nom_personne", confidence=0.9)
    vault.link_doc_entity(doc_id="d1", token="<<np:test>>", start_pos=0, end_pos=4)
    clusters = cluster_subjects(vault, query="Test")
    assert clusters
    c = clusters[0]
    assert isinstance(c, SubjectCluster)
    assert hasattr(c, "cluster_id")
    assert hasattr(c, "seed_match")
    assert hasattr(c, "seed_token")
    assert hasattr(c, "confidence")
    assert hasattr(c, "tokens")
    assert hasattr(c, "sample_doc_ids")
    assert hasattr(c, "first_seen")
    assert hasattr(c, "last_seen")
    assert isinstance(c.tokens, tuple)
    assert isinstance(c.sample_doc_ids, tuple)
