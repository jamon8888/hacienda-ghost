"""Tests that doc_authors are anonymised before being stored in documents_meta.

Without this, the kreuzberg-extracted PDF/Office author field would
flow through documents_meta and surface raw names in the Phase 2
processing_register.
"""
from __future__ import annotations

import pytest

from piighost.service.doc_metadata_extractor import (
    build_metadata, _anonymise_authors,
)


def test_anonymise_authors_replaces_names_with_placeholders():
    """A list of raw names must be transformed into deterministic
    placeholder tokens via the same hash scheme as parties."""
    out = _anonymise_authors(["Marie Dupont", "Jean Martin"])
    # Each entry should be a placeholder token, never a raw name
    assert "Marie Dupont" not in out
    assert "Jean Martin" not in out
    # Should look like <<author:HASH8>> or similar
    for entry in out:
        assert entry.startswith("<<")
        assert entry.endswith(">>")


def test_anonymise_authors_handles_empty():
    assert _anonymise_authors([]) == []
    assert _anonymise_authors(None) == []


def test_anonymise_authors_handles_blank_strings():
    """Whitespace-only entries must not produce empty tokens."""
    out = _anonymise_authors(["  ", "", "Marie Dupont"])
    assert len(out) == 1
    assert "Marie Dupont" not in out[0]


def test_anonymise_authors_deterministic():
    """Same input → same token (cluster-stable across re-extractions)."""
    a = _anonymise_authors(["Marie Dupont"])
    b = _anonymise_authors(["Marie Dupont"])
    assert a == b


def test_anonymise_authors_dedups():
    """Duplicate names → single token (set semantics, but deterministic order)."""
    out = _anonymise_authors(["Marie Dupont", "Marie Dupont"])
    assert len(out) == 1


def test_build_metadata_doc_authors_never_contain_raw_names(tmp_path):
    """E2E: even if kreuzberg returns raw author strings, they must
    NEVER reach DocumentMetadata.doc_authors as raw names."""
    project_root = tmp_path / "p"
    project_root.mkdir()
    fp = project_root / "doc.pdf"
    fp.write_text("x")

    meta = build_metadata(
        doc_id="abc",
        file_path=fp,
        project_root=project_root,
        content="some content",
        kreuzberg_meta={
            "authors": ["Marie Dupont", "Jean Martin"],
            "format_type": "pdf",
        },
        detections=[],
    )
    # The raw names must NOT appear in doc_authors
    serialized = "|".join(meta.doc_authors)
    assert "Marie Dupont" not in serialized
    assert "Jean Martin" not in serialized
    # We should have 2 placeholder tokens (one per unique author)
    assert len(meta.doc_authors) == 2
