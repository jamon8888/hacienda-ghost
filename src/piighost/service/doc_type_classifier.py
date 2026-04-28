"""Heuristic classifier for document type — Phase 0 baseline.

Cascade:
  1. Filename regex patterns (high confidence, ~0.85-0.95)
  2. Structural patterns in the first ~1500 chars of extracted text
     (medium confidence, ~0.7-0.85)
  3. Fallback: ``("autre", 0.0)``

Pure function, no I/O, no model. Easily extensible by editing the
two pattern tables below. GLiNER2 with custom labels is a future
upgrade path (Phase 1+ optional) that would slot in as step 1.5
without changing the public API.
"""
from __future__ import annotations

import re
from typing import Literal

DocType = Literal[
    "contrat", "facture", "email", "courrier", "acte_notarie",
    "jugement", "decision_administrative", "attestation",
    "cv", "note_interne", "autre",
]

# (regex, doc_type, confidence) — checked in order, first match wins.
# NOTE: We use (?<![a-zA-Z]) / (?![a-zA-Z]) instead of \b because
# filenames use underscores as word separators, and underscore IS a
# \w character so \b does not fire between a letter and '_'.
#
# Trailing optional ``s?`` handles plural forms (``invoices``,
# ``contracts``, ``factures``, etc.) — caught from real e2e smoke
# against piighost-test-multi-format/{client1,client2}/invoices.txt
# and contracts.{pdf,jsonl}. The plural ``s`` is followed by a
# non-letter (separator or extension), so the (?![a-zA-Z]) lookahead
# still fires correctly. ``acte``/``notari`` keep their existing form
# (their morphology doesn't pluralize the same way).
_FILENAME_PATTERNS: tuple[tuple[re.Pattern[str], DocType, float], ...] = (
    (re.compile(r"\.(eml|msg)$", re.I),
     "email",              0.95),
    (re.compile(r"(?<![a-zA-Z])(contract|contrat|sla|nda|mou)s?(?![a-zA-Z])", re.I),
     "contrat",            0.90),
    (re.compile(r"(?<![a-zA-Z])(invoice|facture|fac)s?(?![a-zA-Z])", re.I),
     "facture",            0.90),
    (re.compile(r"(?<![a-zA-Z])(cv|resume|curriculum)s?(?![a-zA-Z])", re.I),
     "cv",                 0.85),
    (re.compile(r"(?<![a-zA-Z])(courrier|letter|lettre)s?(?![a-zA-Z])", re.I),
     "courrier",           0.85),
    (re.compile(r"(?<![a-zA-Z])(acte|notari)(?![a-zA-Z])", re.I),
     "acte_notarie",       0.80),
    (re.compile(r"(?<![a-zA-Z])(jugement|judgment|arret|arrêt)s?(?![a-zA-Z])", re.I),
     "jugement",           0.85),
    (re.compile(r"(?<![a-zA-Z])(attestation|certificat)s?(?![a-zA-Z])", re.I),
     "attestation",        0.80),
    (re.compile(r"(?<![a-zA-Z])(note|memo)s?(?![a-zA-Z])", re.I),
     "note_interne",       0.70),
)

# (regex, doc_type, confidence) — applied to first 1500 chars of content
_STRUCTURAL_PATTERNS: tuple[tuple[re.Pattern[str], DocType, float], ...] = (
    # Email headers (multiline, looking for both From/Sender + Subject within head)
    (re.compile(
        r"^(From|De|Sender)\s*:.*\n(?:.*\n){0,5}^(Subject|Objet)\s*:",
        re.I | re.M,
     ), "email", 0.90),
    # Contract structural markers
    (re.compile(
        r"\b(Article 1\b|Considérant|Le soussigné|Entre les soussignés|Préambule)\b",
        re.I,
     ), "contrat", 0.80),
    # Invoice markers
    (re.compile(
        r"(Total HT|TVA|Sous-total|Net à payer|N° de facture|Invoice number)",
        re.I,
     ), "facture", 0.80),
    # Notarial header
    (re.compile(
        r"\b(Maître\s+\w+,?\s+notaire|Office Notarial|reçu en notre office)\b",
        re.I,
     ), "acte_notarie", 0.75),
    # Judgment / court decision
    (re.compile(
        r"\b(Tribunal|Cour d['']Appel|Audience|Au nom du peuple français)\b",
        re.I,
     ), "jugement", 0.75),
    # CV structural
    (re.compile(
        r"\b(Curriculum Vitae|Expériences professionnelles|Compétences techniques)\b",
        re.I,
     ), "cv", 0.75),
)

_HEAD_LIMIT = 1500


def classify(
    filename: str,
    text_head: str,
    *,
    title_hint: str | None = None,
    format_hint: str | None = None,
) -> tuple[DocType, float]:
    """Return ``(doc_type, confidence in [0.0, 1.0])``.

    ``filename`` is the basename; ``text_head`` is the first ~1500 chars
    of extracted text. ``title_hint`` and ``format_hint`` come from
    kreuzberg metadata and are checked as a tiebreaker when the file
    text is empty (e.g. encrypted PDFs).
    """
    # 1. Filename rules
    for pattern, doctype, conf in _FILENAME_PATTERNS:
        if pattern.search(filename):
            return doctype, conf

    # 2. Structural patterns
    head = text_head[:_HEAD_LIMIT] if text_head else ""
    if head:
        for pattern, doctype, conf in _STRUCTURAL_PATTERNS:
            if pattern.search(head):
                return doctype, conf

    # 3. Title hint as tiebreaker for empty text (encrypted, OCR failure)
    if title_hint:
        for pattern, doctype, conf in _FILENAME_PATTERNS:
            if pattern.search(title_hint):
                return doctype, max(conf - 0.15, 0.5)  # slightly less confident

    # 4. Fallback
    return "autre", 0.0
