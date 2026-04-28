"""Extractor regex coverage."""
from __future__ import annotations

import pytest

from piighost.legal.ref_extractor import extract_references
from piighost.legal.reference_models import LegalReference, LegalRefType


def test_extract_article_code():
    refs = extract_references("L'article 1240 du Code civil dispose…")
    assert len(refs) == 1
    assert refs[0].ref_type == LegalRefType.ARTICLE_CODE
    assert refs[0].numero == "1240"
    assert refs[0].code == "Code civil"


def test_extract_article_with_prefix():
    refs = extract_references("art. L. 121-1 C. com.")
    assert len(refs) == 1
    assert refs[0].ref_type == LegalRefType.ARTICLE_CODE
    assert refs[0].numero == "121-1" or refs[0].numero == "L. 121-1"
    assert "commerce" in (refs[0].code or "").lower()


def test_extract_loi_with_numero():
    refs = extract_references("loi n°78-17 du 6 janvier 1978")
    assert any(r.ref_type == LegalRefType.LOI for r in refs)
    loi = next(r for r in refs if r.ref_type == LegalRefType.LOI)
    assert loi.text_id == "78-17"
    assert "1978" in loi.date


def test_extract_decret():
    refs = extract_references("décret n°2019-536 du 29 mai 2019")
    decrets = [r for r in refs if r.ref_type == LegalRefType.DECRET]
    assert len(decrets) == 1
    assert decrets[0].text_id == "2019-536"


def test_extract_jurisprudence():
    refs = extract_references("Cass. civ. 1re, 15 mars 2023, n°21-12.345")
    juri = [r for r in refs if r.ref_type == LegalRefType.JURISPRUDENCE]
    assert len(juri) == 1
    assert juri[0].pourvoi == "21-12.345"
    assert "2023" in juri[0].date


def test_extract_multiple_refs_in_paragraph():
    text = (
        "Le présent litige relève des articles 1240 et 1241 du Code civil, "
        "tels qu'interprétés par Cass. civ. 1re, 15 mars 2023, n°21-12.345."
    )
    refs = extract_references(text)
    # At minimum: 1240, 1241, jurisprudence — 3 refs
    assert len(refs) >= 3
    types = {r.ref_type for r in refs}
    assert LegalRefType.ARTICLE_CODE in types
    assert LegalRefType.JURISPRUDENCE in types


def test_extract_no_refs_returns_empty():
    assert extract_references("Je suis allé acheter du pain.") == []


def test_extract_ref_ids_are_unique_and_sequential():
    text = "article 1240, article 1241, article 1242 du Code civil"
    refs = extract_references(text)
    ids = [r.ref_id for r in refs]
    assert len(ids) == len(set(ids))  # unique
    assert ids == sorted(ids)  # sequential


def test_extract_preserves_position():
    """ref.position points to start char in source."""
    text = "Bonjour. L'article 1240 du Code civil."
    refs = extract_references(text)
    assert len(refs) >= 1
    art = refs[0]
    assert art.position >= 9  # after "Bonjour. "
    assert text[art.position : art.position + len("article")].lower() == "article"
