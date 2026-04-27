"""Tests for the doc_type heuristic classifier (Phase 0 baseline)."""
from __future__ import annotations

import pytest

from piighost.service.doc_type_classifier import classify


@pytest.mark.parametrize("filename,expected", [
    ("contract_2024.pdf", "contrat"),
    ("contrat_acme.docx", "contrat"),
    ("nda-final.pdf", "contrat"),
    ("sla_v2.docx", "contrat"),
])
def test_filename_contracts(filename, expected):
    label, conf = classify(filename, "")
    assert label == expected
    assert conf >= 0.85


@pytest.mark.parametrize("filename", ["facture_001.pdf", "invoice_2024.pdf", "FAC-2024-001.pdf"])
def test_filename_invoices(filename):
    label, conf = classify(filename, "")
    assert label == "facture"
    assert conf >= 0.85


@pytest.mark.parametrize("filename", ["mail_2024.eml", "message.msg", "email-bonjour.eml"])
def test_filename_emails(filename):
    label, conf = classify(filename, "")
    assert label == "email"
    assert conf >= 0.9


@pytest.mark.parametrize("filename", ["cv_dupont.pdf", "resume_martin.docx"])
def test_filename_cvs(filename):
    label, conf = classify(filename, "")
    assert label == "cv"
    assert conf >= 0.85


def test_structural_contract_in_text_head():
    label, conf = classify(
        "Document_v3_FINAL.pdf",
        "Article 1 - Objet du contrat\nLe présent contrat a pour objet...",
    )
    assert label == "contrat"
    assert conf >= 0.7


def test_structural_invoice_in_text_head():
    label, conf = classify(
        "Doc_2024.pdf",
        "Total HT: 1 200,00 €\nTVA 20%: 240,00 €\nNet à payer: 1 440,00 €",
    )
    assert label == "facture"
    assert conf >= 0.7


def test_structural_email_in_text_head():
    label, conf = classify(
        "msg.eml",
        "From: jean@acme.fr\nSubject: Réunion lundi\nDate: 2026-04-15\n\nBonjour,",
    )
    assert label == "email"
    assert conf >= 0.85


def test_structural_acte_notarie():
    label, conf = classify(
        "doc.pdf",
        "Maître Pierre Bernard, notaire à Paris\nReçu en notre office...",
    )
    assert label == "acte_notarie"
    assert conf >= 0.7


def test_structural_jugement():
    label, conf = classify(
        "decision.pdf",
        "République Française\nAu nom du peuple français\nTribunal de grande instance...",
    )
    assert label == "jugement"
    assert conf >= 0.7


def test_structural_cv():
    label, conf = classify(
        "doc.pdf",
        "Curriculum Vitae\nExpériences professionnelles\nFormation\nLangues",
    )
    assert label == "cv"
    assert conf >= 0.7


def test_unknown_returns_autre_zero_confidence():
    label, conf = classify("random_doc.pdf", "Some random unstructured text without keywords.")
    assert label == "autre"
    assert conf == 0.0


def test_filename_wins_over_structural_when_both_match():
    """Filename rule (0.9) beats structural (0.7+) when both fire."""
    label, conf = classify(
        "facture_2024.pdf",
        "Article 1 - Le présent contrat...",
    )
    assert label == "facture"
    assert conf >= 0.85


def test_classify_is_deterministic():
    a = classify("contract.pdf", "Article 1 - Objet")
    b = classify("contract.pdf", "Article 1 - Objet")
    assert a == b


def test_classify_handles_empty_inputs():
    label, conf = classify("", "")
    assert label == "autre"
    assert conf == 0.0


def test_classify_returns_safe_when_text_head_is_huge():
    """Confirm no quadratic blowup on large inputs."""
    huge_text = "lorem ipsum " * 10000
    label, conf = classify("doc.pdf", huge_text)
    assert label == "autre"  # no patterns match
    assert conf == 0.0
