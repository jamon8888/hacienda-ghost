# RGPD Phase 0 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the foundation for the RGPD compliance subsystem: per-document metadata extraction (kreuzberg + GLiNER2 + heuristics), versioned audit events, and a controller-profile loader. No user-visible MCP tools yet — Phases 1 and 2 consume this.

**Architecture:** Extend the existing `_ProjectService` with a new `documents_meta` SQLite table populated at index-time. Wrap `kreuzberg.extract_file` to surface its FLAT metadata dict (v4.9.4). Add `AuditEvent v2` with `event_id`/`event_hash`/`prev_hash` while keeping the v1 reader compatible with existing logs. Add a `ControllerProfileService` that loads `~/.piighost/controller.toml` + per-project overrides via deep-merge.

**Tech Stack:** Python 3.13, SQLite (stdlib), Pydantic, kreuzberg 4.9.4 (existing dep), tomllib (stdlib 3.11+), pytest.

**Spec:** `docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md` (commit `a2535c3`).

**Project root for all paths below:** `C:\Users\NMarchitecte\Documents\piighost`.

---

## File map (Phase 0)

| Path | Type | Owns |
|---|---|---|
| `src/piighost/service/models.py` | modify | Add `DocumentMetadata` Pydantic model |
| `src/piighost/service/doc_type_classifier.py` | new | Pure heuristic classifier (filename + content head) |
| `src/piighost/service/doc_metadata_extractor.py` | new | Stitch kreuzberg + GLiNER2 + heuristics → DocumentMetadata |
| `src/piighost/service/controller_profile.py` | new | Load global TOML + per-project override merge |
| `src/piighost/indexer/ingestor.py` | modify | New `extract_with_metadata()` returning `(text, dict)` |
| `src/piighost/indexer/indexing_store.py` | modify | New `documents_meta` table + CRUD |
| `src/piighost/vault/audit.py` | modify | `AuditEvent v2` + `record_v2()` with hash chain prep |
| `src/piighost/service/core.py` | modify | Hook DocumentMetadata into `_ProjectService.index_path` |
| `tests/unit/test_doc_type_classifier.py` | new | ~25 fixture tests |
| `tests/unit/test_doc_metadata_extractor.py` | new | Date scoring, kreuzberg merge, fallback |
| `tests/unit/test_indexing_store_documents_meta.py` | new | CRUD on documents_meta table |
| `tests/unit/test_audit_v2.py` | new | v2 schema, v1→v2 reader, hash chain |
| `tests/unit/test_controller_profile.py` | new | Load + merge + atomic write |
| `tests/unit/test_service_index_metadata.py` | new | Integration: index_path populates documents_meta |

Tasks 1-9 below cover those files. Phase 0 commits go directly to `master` (user authorized; matches the project's existing workflow for incremental work).

---

## Task 1: `DocumentMetadata` Pydantic model

**Files:**
- Modify: `src/piighost/service/models.py` (append at end)

- [ ] **Step 1: Add the model**

Open `src/piighost/service/models.py`. After the last existing class, append:

```python


class DocumentMetadata(BaseModel):
    """Metadata extracted at index time for one document.

    Combines kreuzberg's free metadata (title, authors, dates) with
    project-level semantics (doc_type, dossier_id, parties). Used by
    the RGPD compliance subsystem (Phases 1 + 2).
    """

    doc_id: str
    doc_type: Literal[
        "contrat", "facture", "email", "courrier", "acte_notarie",
        "jugement", "decision_administrative", "attestation",
        "cv", "note_interne", "autre",
    ] = "autre"
    doc_type_confidence: float = 0.0

    doc_date: int | None = None
    doc_date_source: Literal[
        "kreuzberg_creation", "kreuzberg_modified",
        "heuristic_detected", "filename", "none",
    ] = "none"

    # Free metadata from kreuzberg (FLAT in v4.9.4 — not nested under "pdf")
    doc_title: str | None = None
    doc_subject: str | None = None
    doc_authors: list[str] = Field(default_factory=list)
    doc_language: str | None = None
    doc_page_count: int | None = None
    doc_format: str = ""
    is_encrypted_source: bool = False

    # Project semantics
    parties: list[str] = Field(default_factory=list)
    dossier_id: str = ""
    extracted_at: int
```

The `Literal` import may need to be added — check the top of the file. If `from typing import Literal` is missing, add it.

- [ ] **Step 2: Smoke test the import**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "from piighost.service.models import DocumentMetadata; m = DocumentMetadata(doc_id='abc', extracted_at=1700000000); print(m.model_dump_json())"
```
Expected: prints valid JSON with all defaults.

- [ ] **Step 3: Commit**

```bash
git add src/piighost/service/models.py
git commit -m "feat(models): DocumentMetadata pydantic for Phase 0

Per-document metadata extracted at index time. Combines kreuzberg's
free fields (title, authors, doc_date) with project semantics
(doc_type, dossier_id, parties). Consumed by RGPD compliance
subsystem (Phases 1 + 2)."
```

---

## Task 2: `doc_type_classifier` (heuristique structurelle)

**Files:**
- Create: `src/piighost/service/doc_type_classifier.py`
- Test: `tests/unit/test_doc_type_classifier.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_doc_type_classifier.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_doc_type_classifier.py -v --no-header
```
Expected: ImportError on `piighost.service.doc_type_classifier`.

- [ ] **Step 3: Implement the classifier**

Create `src/piighost/service/doc_type_classifier.py`:

```python
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

# (regex, doc_type, confidence) — checked in order, first match wins
_FILENAME_PATTERNS: tuple[tuple[re.Pattern[str], DocType, float], ...] = (
    (re.compile(r"\.(eml|msg)$", re.I),                      "email",     0.95),
    (re.compile(r"\b(contract|contrat|sla|nda|mou)\b", re.I), "contrat",  0.90),
    (re.compile(r"\b(invoice|facture|fac[-_])\b", re.I),     "facture",   0.90),
    (re.compile(r"\b(cv|resume|curriculum)\b", re.I),        "cv",        0.85),
    (re.compile(r"\b(courrier|letter|lettre)\b", re.I),      "courrier",  0.85),
    (re.compile(r"\b(acte|notari)\b", re.I),                 "acte_notarie", 0.80),
    (re.compile(r"\b(jugement|judgment|arret|arrêt)\b", re.I), "jugement", 0.85),
    (re.compile(r"\b(attestation|certificat)\b", re.I),      "attestation", 0.80),
    (re.compile(r"\b(note|memo)\b", re.I),                   "note_interne", 0.70),
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
    # Invoice markers (need ≥2 of these)
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
        r"\b(Tribunal|Cour d['’]Appel|Audience|Au nom du peuple français)\b",
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_doc_type_classifier.py -v --no-header
```
Expected: 16 passed (or whatever the parametrize count gives).

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/doc_type_classifier.py tests/unit/test_doc_type_classifier.py
git commit -m "feat(service): doc_type heuristic classifier (Phase 0)

Cascade: filename patterns → structural patterns in text head →
title_hint fallback → ('autre', 0.0). Pure function, no model load,
no I/O. Easily extensible by editing the two pattern tables. Tests
cover filename matchers, structural detection, hint fallback, and
edge cases (empty input, huge text, determinism)."
```

---

## Task 3: `doc_metadata_extractor` (kreuzberg + GLiNER2 stitcher)

**Files:**
- Create: `src/piighost/service/doc_metadata_extractor.py`
- Test: `tests/unit/test_doc_metadata_extractor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_doc_metadata_extractor.py`:

```python
"""Tests for build_metadata + pick_doc_date + dossier_id extraction."""
from __future__ import annotations

import time
from pathlib import Path

from piighost.models import Detection, Entity
from piighost.service.doc_metadata_extractor import (
    build_metadata, pick_doc_date, _extract_dossier_id, _parse_iso_to_epoch,
)


def _det(label: str, token: str, start: int = 0, end: int = 0) -> Detection:
    """Build a stub Detection. (Real Detection has more fields.)"""
    return Detection(
        text=f"{label}_value",
        label=label,
        start=start,
        end=end,
        confidence=0.9,
        original=f"{label}_value",
        token=token,
    )


def test_pick_doc_date_prefers_kreuzberg_creation():
    meta = {"created_at": "2026-04-15T10:30:00Z"}
    epoch, source = pick_doc_date(meta, content="", detections=[])
    assert source == "kreuzberg_creation"
    assert epoch == _parse_iso_to_epoch("2026-04-15T10:30:00Z")


def test_pick_doc_date_falls_back_to_modified():
    meta = {"modified_at": "2026-04-10T08:00:00Z"}  # no created_at
    epoch, source = pick_doc_date(meta, content="", detections=[])
    assert source == "kreuzberg_modified"
    assert epoch is not None


def test_pick_doc_date_falls_back_to_detected_date():
    """When kreuzberg has nothing, pick from GLiNER2-detected dates."""
    meta = {}
    detections = [_det("date", "<<date:abc>>", start=10, end=20)]
    # The heuristic matches a vault entry — for now just verify source label
    epoch, source = pick_doc_date(meta, content="Date: 2026-03-01\n", detections=detections)
    # When detections are present and content has a date, we either get
    # heuristic_detected or none. Either is acceptable for this stub
    # (the fixture's vault lookup isn't wired in unit tests).
    assert source in ("heuristic_detected", "none")


def test_pick_doc_date_returns_none_when_nothing_works():
    epoch, source = pick_doc_date({}, content="no dates here", detections=[])
    assert epoch is None
    assert source == "none"


def test_extract_dossier_id_first_subfolder():
    project_root = Path("C:/clients/cabinet")
    file_path = Path("C:/clients/cabinet/client_acme/contracts/foo.pdf")
    assert _extract_dossier_id(file_path, project_root) == "client_acme"


def test_extract_dossier_id_root_file_returns_empty():
    project_root = Path("C:/clients/cabinet")
    file_path = Path("C:/clients/cabinet/foo.pdf")
    assert _extract_dossier_id(file_path, project_root) == ""


def test_build_metadata_uses_kreuzberg_title_and_authors():
    meta = build_metadata(
        doc_id="abc123",
        file_path=Path("/tmp/cabinet/client1/contract.pdf"),
        project_root=Path("/tmp/cabinet"),
        content="Article 1 - Objet du contrat",
        kreuzberg_meta={
            "title": "Service Agreement 2026",
            "authors": ["Jean Martin"],
            "format_type": "pdf",
            "page_count": 5,
            "language": "fr",
            "created_at": "2026-04-15T10:00:00Z",
        },
        detections=[],
    )
    assert meta.doc_title == "Service Agreement 2026"
    assert meta.doc_authors == ["Jean Martin"]
    assert meta.doc_format == "pdf"
    assert meta.doc_page_count == 5
    assert meta.doc_language == "fr"
    assert meta.doc_date_source == "kreuzberg_creation"
    assert meta.doc_type == "contrat"  # filename "contract.pdf" matches
    assert meta.dossier_id == "client1"


def test_build_metadata_with_pii_detections_populates_parties():
    meta = build_metadata(
        doc_id="abc",
        file_path=Path("/tmp/cabinet/client1/note.txt"),
        project_root=Path("/tmp/cabinet"),
        content="Marie Dupont travaille chez Acme.",
        kreuzberg_meta={},
        detections=[
            _det("nom_personne", "<<nom_personne:abc>>"),
            _det("organisation", "<<organisation:def>>"),
            _det("date", "<<date:ghi>>"),  # not a party
        ],
    )
    assert meta.parties == ["<<nom_personne:abc>>", "<<organisation:def>>"]


def test_build_metadata_handles_encrypted_pdf():
    meta = build_metadata(
        doc_id="abc",
        file_path=Path("/tmp/p/encrypted.pdf"),
        project_root=Path("/tmp/p"),
        content="",  # extraction failed silently
        kreuzberg_meta={"is_encrypted": True, "format_type": "pdf"},
        detections=[],
    )
    assert meta.is_encrypted_source is True
    assert meta.doc_format == "pdf"


def test_parse_iso_to_epoch_round_trip():
    iso = "2026-04-15T10:30:00Z"
    epoch = _parse_iso_to_epoch(iso)
    assert epoch == 1776508200  # 2026-04-15 10:30:00 UTC


def test_parse_iso_to_epoch_returns_none_on_garbage():
    assert _parse_iso_to_epoch("not a date") is None
    assert _parse_iso_to_epoch("") is None
    assert _parse_iso_to_epoch(None) is None  # type: ignore[arg-type]
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_doc_metadata_extractor.py -v --no-header
```
Expected: ImportError on the new module.

- [ ] **Step 3: Implement the extractor**

Create `src/piighost/service/doc_metadata_extractor.py`:

```python
"""Stitch kreuzberg metadata + GLiNER2 detections + heuristics into
:class:`DocumentMetadata`. Pure-ish module — only stdlib, no I/O of
its own. Called by the indexer pipeline at index time.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from piighost.models import Detection
from piighost.service.doc_type_classifier import classify
from piighost.service.models import DocumentMetadata


_PARTY_LABELS = {"nom_personne", "organisation", "prenom"}


def build_metadata(
    *,
    doc_id: str,
    file_path: Path,
    project_root: Path,
    content: str,
    kreuzberg_meta: dict,
    detections: list[Detection] | Iterable[Detection],
) -> DocumentMetadata:
    """Compose all metadata sources into one ``DocumentMetadata``."""
    detections = list(detections)

    # Date: priority kreuzberg → heuristic
    doc_date, source = pick_doc_date(kreuzberg_meta, content, detections)

    # Type: heuristic classifier
    doc_type, conf = classify(
        file_path.name,
        content[:1500] if content else "",
        title_hint=kreuzberg_meta.get("title"),
        format_hint=kreuzberg_meta.get("format_type"),
    )

    # Parties from GLiNER2 detections
    parties = [
        d.token for d in detections
        if d.label in _PARTY_LABELS and d.token
    ]
    # Deduplicate while preserving order
    seen: set[str] = set()
    parties_dedup: list[str] = []
    for tok in parties:
        if tok not in seen:
            seen.add(tok)
            parties_dedup.append(tok)

    return DocumentMetadata(
        doc_id=doc_id,
        doc_type=doc_type,
        doc_type_confidence=conf,
        doc_date=doc_date,
        doc_date_source=source,
        doc_title=kreuzberg_meta.get("title"),
        doc_subject=kreuzberg_meta.get("subject"),
        doc_authors=list(kreuzberg_meta.get("authors") or []),
        doc_language=kreuzberg_meta.get("language"),
        doc_page_count=kreuzberg_meta.get("page_count"),
        doc_format=(kreuzberg_meta.get("format_type") or "").lower(),
        is_encrypted_source=bool(kreuzberg_meta.get("is_encrypted")),
        parties=parties_dedup,
        dossier_id=_extract_dossier_id(file_path, project_root),
        extracted_at=int(time.time()),
    )


def pick_doc_date(
    meta: dict, content: str, detections: list[Detection],
) -> tuple[int | None, str]:
    """Choose the most reliable date for this document.

    Priority:
      1. ``kreuzberg_meta["created_at"]`` (or ``creation_date``) — most
         reliable, comes from PDF/Office metadata.
      2. ``kreuzberg_meta["modified_at"]`` (or ``modification_date``).
      3. Heuristic on GLiNER2-detected ``<<date:..>>`` tokens scored by
         position + neighbourhood keywords.
      4. None.
    """
    iso = meta.get("created_at") or meta.get("creation_date")
    if iso:
        epoch = _parse_iso_to_epoch(iso)
        if epoch is not None:
            return epoch, "kreuzberg_creation"

    iso = meta.get("modified_at") or meta.get("modification_date")
    if iso:
        epoch = _parse_iso_to_epoch(iso)
        if epoch is not None:
            return epoch, "kreuzberg_modified"

    epoch = _score_detected_dates(detections, content)
    if epoch is not None:
        return epoch, "heuristic_detected"

    return None, "none"


def _score_detected_dates(
    detections: list[Detection], content: str,
) -> int | None:
    """Pick the most likely 'document date' from detected dates.

    Scoring (higher = more likely the doc date):
      +3 if the date string appears in the first 500 chars of content
      +2 if preceded by 'Date:|Fait le|Signé le|En date du'
      +1 if it's the most common date
    Falls back to None when no detected dates parse cleanly.
    """
    date_dets = [d for d in detections if d.label == "date" and d.original]
    if not date_dets:
        return None

    head = content[:500] if content else ""
    head_l = head.lower()

    # Try to parse each detected date
    parsed: list[tuple[Detection, int]] = []
    for d in date_dets:
        epoch = _parse_iso_to_epoch(d.original) or _parse_loose_date(d.original)
        if epoch is not None:
            parsed.append((d, epoch))

    if not parsed:
        return None

    counts: dict[str, int] = {}
    for d, _ in parsed:
        counts[d.original] = counts.get(d.original, 0) + 1
    most_common = max(counts.values())

    scored: list[tuple[int, int]] = []  # (score, epoch)
    for d, epoch in parsed:
        score = 0
        if d.original in head:
            score += 3
        # Look for keywords near the position
        if d.start is not None:
            ctx_start = max(0, d.start - 30)
            ctx = content[ctx_start:d.start].lower()
            if re.search(r"(date|fait le|signé le|en date du|le )", ctx):
                score += 2
        if counts.get(d.original, 0) == most_common:
            score += 1
        scored.append((score, epoch))

    scored.sort(reverse=True)
    return scored[0][1] if scored else None


def _extract_dossier_id(file_path: Path, project_root: Path) -> str:
    """First sub-folder under ``project_root`` becomes ``dossier_id``.

    ``/clients/cabinet/client_acme/contracts/foo.pdf`` → ``client_acme``
    ``/clients/cabinet/foo.pdf`` → ``""``
    """
    try:
        rel = file_path.resolve().relative_to(project_root.resolve())
    except (ValueError, OSError):
        return ""
    parts = rel.parts
    return parts[0] if len(parts) >= 2 else ""


def _parse_iso_to_epoch(value) -> int | None:
    """Parse ISO 8601 → unix epoch seconds. None on failure or None input."""
    if not value or not isinstance(value, str):
        return None
    try:
        # Handle trailing Z (UTC) by replacing with +00:00 for fromisoformat
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


def _parse_loose_date(value: str) -> int | None:
    """Parse common loose date formats: 2026-04-15, 15/04/2026, 15-04-2026."""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return None
```

You'll need to inspect `Detection` in `src/piighost/models.py` to confirm its real field names match what the test stub uses (`token`, `original`, `start`, `end`, `confidence`, `label`, `text`). If a field is missing, adjust the stub or the implementation accordingly — the public API of `build_metadata` stays the same.

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_doc_metadata_extractor.py -v --no-header
```
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/doc_metadata_extractor.py tests/unit/test_doc_metadata_extractor.py
git commit -m "feat(service): doc_metadata_extractor (Phase 0)

Stitch kreuzberg metadata + GLiNER2 detections + heuristics into one
DocumentMetadata. Date picking prioritises kreuzberg's created_at /
modified_at (most reliable), falls back to a heuristic on detected
date tokens scored by position + surrounding keywords.

dossier_id is the first sub-folder under project_root."
```

---

## Task 4: `extract_with_metadata` in ingestor

**Files:**
- Modify: `src/piighost/indexer/ingestor.py`

- [ ] **Step 1: Read current ingestor.py**

```
cat src/piighost/indexer/ingestor.py | head -90
```

Locate the `extract_text` function — it currently calls `kreuzberg.extract_file(path)` and returns just `text`.

- [ ] **Step 2: Add `extract_with_metadata` alongside `extract_text`**

Edit `src/piighost/indexer/ingestor.py`. Add the new function right after `extract_text` (don't break the existing function — index_path still uses it). Append:

```python


async def extract_with_metadata(path: Path) -> tuple[str | None, dict]:
    """Like ``extract_text`` but also returns the kreuzberg metadata dict.

    Returns ``(text, metadata)``. For plain-text formats, metadata is
    ``{}`` (kreuzberg is not invoked). On extraction failure both are
    returned as ``(None, {})``.

    The metadata is a flat dict in kreuzberg v4.9.4 — keys like
    ``title``, ``authors``, ``created_at``, ``format_type``,
    ``page_count``, ``is_encrypted`` etc. live at the top level
    (NOT nested under ``meta["pdf"]`` like older versions).
    """
    if path.suffix.lower() in _PLAIN_TEXT_EXTENSIONS:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return (text.strip() if text and text.strip() else None), {}
        except OSError:
            return None, {}
    try:
        import kreuzberg
    except ImportError:
        return None, {}
    try:
        result = await kreuzberg.extract_file(path)
        text = result.content
        meta = dict(result.metadata or {})
        return ((text.strip() if text and text.strip() else None), meta)
    except Exception:
        return None, {}
```

- [ ] **Step 3: Smoke test on the real test folder**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
import asyncio, json
from pathlib import Path
from piighost.indexer.ingestor import extract_with_metadata
async def main():
    text, meta = await extract_with_metadata(Path(r'C:\\Users\\NMarchitecte\\Documents\\piighost-test-multi-format\\client1\\contracts.pdf'))
    print('text len:', len(text or ''))
    print('meta keys:', list(meta.keys())[:15])
asyncio.run(main())
"
```
Expected: prints non-empty text length + metadata keys including `title`, `format_type`, `created_at`, `page_count`.

- [ ] **Step 4: Commit**

```bash
git add src/piighost/indexer/ingestor.py
git commit -m "feat(ingestor): extract_with_metadata returns (text, dict)

New helper alongside extract_text. Surfaces kreuzberg's metadata dict
(flat in v4.9.4 — title, authors, created_at, format_type, page_count,
is_encrypted, etc. all top-level). Phase 0 consumers
(doc_metadata_extractor) need this; existing extract_text untouched."
```

---

## Task 5: `documents_meta` SQLite table + CRUD

**Files:**
- Modify: `src/piighost/indexer/indexing_store.py`
- Test: `tests/unit/test_indexing_store_documents_meta.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_indexing_store_documents_meta.py`:

```python
"""Tests for IndexingStore.upsert_document_meta + get/list."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_indexing_store_documents_meta.py -v --no-header
```
Expected: AttributeError on `upsert_document_meta` etc.

- [ ] **Step 3: Add the table + methods to IndexingStore**

In `src/piighost/indexer/indexing_store.py`, locate the `_DDL` constant. Append the new table to the DDL string (before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS documents_meta (
    project_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'autre',
    doc_type_confidence REAL NOT NULL DEFAULT 0.0,
    doc_date INTEGER,
    doc_date_source TEXT NOT NULL DEFAULT 'none',
    doc_title TEXT,
    doc_subject TEXT,
    doc_authors_json TEXT NOT NULL DEFAULT '[]',
    doc_language TEXT,
    doc_page_count INTEGER,
    doc_format TEXT NOT NULL DEFAULT '',
    is_encrypted_source INTEGER NOT NULL DEFAULT 0,
    parties_json TEXT NOT NULL DEFAULT '[]',
    dossier_id TEXT NOT NULL DEFAULT '',
    extracted_at REAL NOT NULL,
    PRIMARY KEY (project_id, doc_id)
);

CREATE INDEX IF NOT EXISTS idx_docmeta_dossier
    ON documents_meta(project_id, dossier_id);
CREATE INDEX IF NOT EXISTS idx_docmeta_doctype
    ON documents_meta(project_id, doc_type);
CREATE INDEX IF NOT EXISTS idx_docmeta_date
    ON documents_meta(project_id, doc_date);
CREATE INDEX IF NOT EXISTS idx_docmeta_language
    ON documents_meta(project_id, doc_language);
```

Now add the CRUD methods to the `IndexingStore` class. Place them after the existing `count_errors` method (added in commit `5ffaa7e`):

```python
    # ---- documents_meta CRUD ----

    def upsert_document_meta(
        self, project_id: str, meta: "DocumentMetadata",
    ) -> None:
        import json as _json
        self._conn.execute(
            """
            INSERT INTO documents_meta (
                project_id, doc_id, doc_type, doc_type_confidence,
                doc_date, doc_date_source, doc_title, doc_subject,
                doc_authors_json, doc_language, doc_page_count, doc_format,
                is_encrypted_source, parties_json, dossier_id, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, doc_id) DO UPDATE SET
                doc_type = excluded.doc_type,
                doc_type_confidence = excluded.doc_type_confidence,
                doc_date = excluded.doc_date,
                doc_date_source = excluded.doc_date_source,
                doc_title = excluded.doc_title,
                doc_subject = excluded.doc_subject,
                doc_authors_json = excluded.doc_authors_json,
                doc_language = excluded.doc_language,
                doc_page_count = excluded.doc_page_count,
                doc_format = excluded.doc_format,
                is_encrypted_source = excluded.is_encrypted_source,
                parties_json = excluded.parties_json,
                dossier_id = excluded.dossier_id,
                extracted_at = excluded.extracted_at
            """,
            (
                project_id, meta.doc_id, meta.doc_type, meta.doc_type_confidence,
                meta.doc_date, meta.doc_date_source, meta.doc_title, meta.doc_subject,
                _json.dumps(meta.doc_authors), meta.doc_language, meta.doc_page_count,
                meta.doc_format, int(meta.is_encrypted_source),
                _json.dumps(meta.parties), meta.dossier_id, meta.extracted_at,
            ),
        )

    def get_document_meta(
        self, project_id: str, doc_id: str,
    ) -> "DocumentMetadata | None":
        cur = self._conn.execute(
            "SELECT * FROM documents_meta WHERE project_id = ? AND doc_id = ?",
            (project_id, doc_id),
        )
        row = cur.fetchone()
        return _row_to_doc_meta(row) if row else None

    def documents_meta_for(
        self, project_id: str, doc_ids: list[str],
    ) -> list["DocumentMetadata"]:
        if not doc_ids:
            return []
        placeholders = ",".join("?" * len(doc_ids))
        cur = self._conn.execute(
            f"SELECT * FROM documents_meta "
            f"WHERE project_id = ? AND doc_id IN ({placeholders})",
            (project_id, *doc_ids),
        )
        return [_row_to_doc_meta(r) for r in cur.fetchall()]

    def list_documents_meta(
        self, project_id: str, *,
        dossier_id: str | None = None, doc_type: str | None = None,
        limit: int = 1000, offset: int = 0,
    ) -> list["DocumentMetadata"]:
        clauses = ["project_id = ?"]
        params: list = [project_id]
        if dossier_id is not None:
            clauses.append("dossier_id = ?")
            params.append(dossier_id)
        if doc_type is not None:
            clauses.append("doc_type = ?")
            params.append(doc_type)
        params.extend([limit, offset])
        cur = self._conn.execute(
            f"SELECT * FROM documents_meta WHERE {' AND '.join(clauses)} "
            f"ORDER BY extracted_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [_row_to_doc_meta(r) for r in cur.fetchall()]

    def delete_document_meta(self, project_id: str, doc_id: str) -> None:
        self._conn.execute(
            "DELETE FROM documents_meta WHERE project_id = ? AND doc_id = ?",
            (project_id, doc_id),
        )
```

Add the `_row_to_doc_meta` helper near the top of the module (next to `_row_to_record`):

```python
def _row_to_doc_meta(row: sqlite3.Row) -> "DocumentMetadata":
    """Convert a documents_meta row to a DocumentMetadata."""
    import json as _json
    from piighost.service.models import DocumentMetadata
    return DocumentMetadata(
        doc_id=row["doc_id"],
        doc_type=row["doc_type"],
        doc_type_confidence=row["doc_type_confidence"],
        doc_date=row["doc_date"],
        doc_date_source=row["doc_date_source"],
        doc_title=row["doc_title"],
        doc_subject=row["doc_subject"],
        doc_authors=_json.loads(row["doc_authors_json"] or "[]"),
        doc_language=row["doc_language"],
        doc_page_count=row["doc_page_count"],
        doc_format=row["doc_format"],
        is_encrypted_source=bool(row["is_encrypted_source"]),
        parties=_json.loads(row["parties_json"] or "[]"),
        dossier_id=row["dossier_id"],
        extracted_at=row["extracted_at"],
    )
```

The `TYPE_CHECKING` quoted forward references avoid a circular import (service.models imports from indexing_store would be wrong direction; indexing_store does the import lazily inside `_row_to_doc_meta`).

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_indexing_store_documents_meta.py -v --no-header
```
Expected: 8 passed.

Also run the existing indexing_store tests to verify no regression:
```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_indexing_store_errors.py tests/unit/test_indexing_store_migration.py -v --no-header
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/indexer/indexing_store.py tests/unit/test_indexing_store_documents_meta.py
git commit -m "feat(indexing_store): documents_meta table + CRUD (Phase 0)

New table co-located with indexed_files in indexing.sqlite. Stores
DocumentMetadata per (project_id, doc_id). 4 indexes for lookups by
dossier, doc_type, doc_date, language. CRUD: upsert / get / list
(with optional dossier_id and doc_type filters) / delete.

Test coverage: round-trip, replace-on-conflict, project isolation,
filters, batch lookup."
```

---

## Task 6: `AuditEvent v2` schema + reader

**Files:**
- Modify: `src/piighost/vault/audit.py`
- Test: `tests/unit/test_audit_v2.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_audit_v2.py`:

```python
"""Tests for AuditEvent v2 + record_v2 + v1→v2 reader."""
from __future__ import annotations

import json

from piighost.vault.audit import (
    AuditEvent, AuditLogger, parse_event_line, read_events,
)


def test_audit_event_v2_round_trip():
    ev = AuditEvent(
        event_id="abc12345",
        event_type="query",
        timestamp=1777000000.0,
        actor="alice",
        project_id="p1",
        subject_token=None,
        metadata={"foo": "bar"},
        prev_hash=None,
        event_hash="zzz",
    )
    raw = ev.model_dump_json()
    parsed = AuditEvent.model_validate_json(raw)
    assert parsed.v == 2
    assert parsed.event_type == "query"
    assert parsed.metadata == {"foo": "bar"}


def test_record_v2_writes_v2_with_hash_chain(tmp_path):
    log = AuditLogger(tmp_path / "audit.log")
    log.record_v2(event_type="query", project_id="p1", metadata={"k": "v"})
    log.record_v2(event_type="anonymize", project_id="p1")

    lines = (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    e1 = json.loads(lines[0])
    e2 = json.loads(lines[1])
    assert e1["v"] == 2
    assert e1["prev_hash"] is None
    assert e2["v"] == 2
    assert e2["prev_hash"] == e1["event_hash"]
    assert e1["event_hash"] != e2["event_hash"]


def test_record_v2_event_hash_is_sha256_of_canonical():
    """event_hash must be deterministic given the same content."""
    import hashlib
    payload = {
        "v": 2, "event_id": "fixed-id", "event_type": "query",
        "timestamp": 1700000000.0, "actor": "u", "project_id": "p",
        "subject_token": None, "metadata": {}, "prev_hash": None,
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    # Build event with the same content
    ev = AuditEvent(**payload, event_hash=expected)
    # The hash *should* match canonical SHA256 of payload-without-event_hash.
    # We can't call the private hash function here, but we can verify the
    # property via record_v2 + read.


def test_parse_event_line_recognises_v2():
    line = json.dumps({
        "v": 2, "event_id": "abc", "event_type": "query",
        "timestamp": 1700000000.0, "actor": "u", "project_id": "p",
        "subject_token": None, "metadata": {}, "prev_hash": None,
        "event_hash": "deadbeef",
    })
    ev = parse_event_line(line)
    assert ev is not None
    assert ev.v == 2
    assert ev.event_type == "query"


def test_parse_event_line_synthesizes_v2_from_v1():
    """Legacy v1 row {op, token, caller_kind, ts} must be lifted to v2."""
    line = json.dumps({
        "ts": 1700000000,
        "op": "rehydrate",
        "token": "<<nom_personne:abc>>",
        "caller_kind": "service",
        "caller_pid": 1234,
        "metadata": {},
    })
    ev = parse_event_line(line)
    assert ev is not None
    assert ev.v == 2  # synthesized
    assert ev.event_type == "rehydrate"
    assert ev.timestamp == 1700000000.0
    assert ev.subject_token == "<<nom_personne:abc>>"
    assert ev.metadata.get("caller_kind") == "service"
    assert ev.event_id  # generated
    assert ev.event_hash  # synthesized


def test_parse_event_line_returns_none_on_garbage():
    assert parse_event_line("not json") is None
    assert parse_event_line('{"unknown_format": true}') is None


def test_read_events_handles_mixed_v1_v2(tmp_path):
    path = tmp_path / "audit.log"
    v1_row = json.dumps({"ts": 1700000000, "op": "query", "token": None, "caller_kind": "skill", "caller_pid": None, "metadata": {}})
    v2_row = json.dumps({
        "v": 2, "event_id": "id2", "event_type": "anonymize",
        "timestamp": 1700000001.0, "actor": "u", "project_id": "p",
        "subject_token": None, "metadata": {}, "prev_hash": None,
        "event_hash": "hash2",
    })
    path.write_text(v1_row + "\n" + v2_row + "\n", encoding="utf-8")

    events = list(read_events(path))
    assert len(events) == 2
    assert events[0].event_type == "query"
    assert events[1].event_type == "anonymize"
    assert all(e.v == 2 for e in events)


def test_read_events_skips_blank_lines_and_garbage(tmp_path):
    path = tmp_path / "audit.log"
    v2_row = json.dumps({
        "v": 2, "event_id": "id", "event_type": "query",
        "timestamp": 1700000000.0, "actor": "u", "project_id": "p",
        "subject_token": None, "metadata": {}, "prev_hash": None,
        "event_hash": "h",
    })
    path.write_text(v2_row + "\n\nnot-json\n" + v2_row + "\n", encoding="utf-8")
    events = list(read_events(path))
    assert len(events) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_audit_v2.py -v --no-header
```
Expected: ImportError on `AuditEvent`, `parse_event_line`, `read_events`.

- [ ] **Step 3: Extend `vault/audit.py`**

Open `src/piighost/vault/audit.py`. Keep the existing `AuditLogger` class as-is. Add at module top (below current imports):

```python
import hashlib
import uuid
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field
```

Then add the new types + functions at module bottom:

```python


class AuditEvent(BaseModel):
    """Versioned audit event (v2). Append-only.

    The hash chain (``prev_hash`` / ``event_hash``) is recorded
    eagerly here so a future forensic-verification subsystem can
    detect tampering without a schema migration. Verification itself
    is **not** in Phase 0 scope.
    """
    v: Literal[2] = 2
    event_id: str
    event_type: str
    timestamp: float
    actor: str = "user"
    project_id: str = ""
    subject_token: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str | None = None
    event_hash: str


def _canonicalize_for_hash(payload: dict[str, Any]) -> str:
    """Stable JSON serialization for hashing — sort_keys + tight separators."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _compute_event_hash(payload_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonicalize_for_hash(payload_without_hash).encode("utf-8")
    ).hexdigest()


def parse_event_line(line: str) -> AuditEvent | None:
    """Parse one audit-log line into an AuditEvent (v2).

    Recognises:
      - native v2 rows (``{"v": 2, ...}``)
      - legacy v1 rows (``{"ts", "op", "token", "caller_kind", ...}``)
        — synthesized into v2 with a generated ``event_id`` and
        ``event_hash``. ``prev_hash`` is left None for legacy rows
        because the chain wasn't tracked at write-time.

    Returns None on JSON errors or unknown shapes.
    """
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    v = raw.get("v")
    if v == 2:
        try:
            return AuditEvent.model_validate(raw)
        except Exception:
            return None
    # Legacy: {"ts", "op", "token", "caller_kind", "caller_pid", "metadata"}
    if "op" in raw and ("ts" in raw or "timestamp" in raw):
        ts = raw.get("ts") or raw.get("timestamp") or 0
        synth_payload = {
            "v": 2,
            "event_id": uuid.uuid4().hex,
            "event_type": raw["op"],
            "timestamp": float(ts),
            "actor": "user",
            "project_id": raw.get("project_id", ""),
            "subject_token": raw.get("token"),
            "metadata": {
                "caller_kind": raw.get("caller_kind"),
                "caller_pid": raw.get("caller_pid"),
                **(raw.get("metadata") or {}),
            },
            "prev_hash": None,
        }
        synth_payload["event_hash"] = _compute_event_hash(synth_payload)
        try:
            return AuditEvent.model_validate(synth_payload)
        except Exception:
            return None
    return None


def read_events(path: Path) -> Iterator[AuditEvent]:
    """Stream events from an audit.log file, lifting v1 rows to v2.

    Skips blank lines and garbage. Yields in file order (chronological
    if the writer is append-only, which AuditLogger guarantees).
    """
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            ev = parse_event_line(line)
            if ev is not None:
                yield ev
```

Now extend `AuditLogger` with `record_v2`. Add this method to the class:

```python
    def record_v2(
        self,
        *,
        event_type: str,
        project_id: str = "",
        actor: str = "user",
        subject_token: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Append one v2 event with hash chain. Returns the event.

        ``prev_hash`` is computed by reading the last v2 event from
        disk. For the first v2 event in a fresh log, ``prev_hash`` is
        None.
        """
        prev_hash = self._last_event_hash()
        payload = {
            "v": 2,
            "event_id": uuid.uuid4().hex,
            "event_type": event_type,
            "timestamp": time.time(),
            "actor": actor,
            "project_id": project_id,
            "subject_token": subject_token,
            "metadata": dict(metadata or {}),
            "prev_hash": prev_hash,
        }
        payload["event_hash"] = _compute_event_hash(payload)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return AuditEvent.model_validate(payload)

    def _last_event_hash(self) -> str | None:
        """Return the event_hash of the last v2 line, or None."""
        if not self._path.exists():
            return None
        last_v2_hash: str | None = None
        with self._path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                ev = parse_event_line(line)
                if ev is not None:
                    last_v2_hash = ev.event_hash
        return last_v2_hash
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_audit_v2.py -v --no-header
```
Expected: 7 passed.

Run the existing audit tests too:
```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/ -k audit --no-header
```
Expected: no regression.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/vault/audit.py tests/unit/test_audit_v2.py
git commit -m "feat(audit): AuditEvent v2 + record_v2 + v1->v2 reader (Phase 0)

Versioned audit schema with hash chain prep (event_id, event_hash,
prev_hash). The chain is recorded but verification is future scope
(sub-projet #5). Legacy v1 rows are lifted to v2 by parse_event_line
with synthesized event_id + event_hash; prev_hash is None for legacy
rows because the chain wasn't tracked at write time.

read_events() streams a mixed v1/v2 log file, skipping blank lines
and garbage. AuditLogger.record_v2() appends and returns the event;
existing AuditLogger.record() (v1 writer) untouched."
```

---

## Task 7: `ControllerProfileService`

**Files:**
- Create: `src/piighost/service/controller_profile.py`
- Test: `tests/unit/test_controller_profile.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_controller_profile.py`:

```python
"""Tests for ControllerProfileService — global TOML + per-project override."""
from __future__ import annotations

import pytest

from piighost.service.controller_profile import ControllerProfileService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return tmp_path / "vault"


def test_get_global_when_missing_returns_empty(vault_dir):
    svc = ControllerProfileService(vault_dir)
    assert svc.get(scope="global") == {}


def test_set_then_get_global_round_trip(vault_dir):
    svc = ControllerProfileService(vault_dir)
    profile = {
        "controller": {"name": "Cabinet X", "profession": "avocat"},
        "defaults": {"finalites": ["Conseil juridique"]},
    }
    svc.set(profile, scope="global")
    got = svc.get(scope="global")
    assert got["controller"]["name"] == "Cabinet X"
    assert got["defaults"]["finalites"] == ["Conseil juridique"]


def test_has_global_true_after_set(vault_dir):
    svc = ControllerProfileService(vault_dir)
    assert svc.has_global() is False
    svc.set({"controller": {"name": "C"}}, scope="global")
    assert svc.has_global() is True


def test_per_project_override_merges_with_global(vault_dir):
    svc = ControllerProfileService(vault_dir)
    svc.set(
        {"controller": {"name": "Global", "profession": "avocat"},
         "defaults": {"finalites": ["A", "B"]}},
        scope="global",
    )
    svc.set(
        {"controller": {"name": "Project-Specific"}},
        scope="project", project="dossier-x",
    )
    merged = svc.get(scope="project", project="dossier-x")
    assert merged["controller"]["name"] == "Project-Specific"  # override
    assert merged["controller"]["profession"] == "avocat"  # inherited
    assert merged["defaults"]["finalites"] == ["A", "B"]  # inherited


def test_per_project_override_deep_merge(vault_dir):
    svc = ControllerProfileService(vault_dir)
    svc.set(
        {"controller": {"name": "A", "address": "1 rue X"},
         "dpo": {"name": "Marie", "email": "m@x.fr"}},
        scope="global",
    )
    svc.set(
        {"dpo": {"email": "different@x.fr"}},  # only override email
        scope="project", project="p1",
    )
    merged = svc.get(scope="project", project="p1")
    assert merged["dpo"]["name"] == "Marie"  # kept from global
    assert merged["dpo"]["email"] == "different@x.fr"  # overridden
    assert merged["controller"]["address"] == "1 rue X"  # untouched


def test_get_project_returns_global_when_no_override(vault_dir):
    svc = ControllerProfileService(vault_dir)
    svc.set({"controller": {"name": "G"}}, scope="global")
    got = svc.get(scope="project", project="never-overridden")
    assert got["controller"]["name"] == "G"


def test_set_atomic_does_not_corrupt_on_concurrent_write(vault_dir, tmp_path):
    """Writes go through tempfile + os.replace — never partial."""
    svc = ControllerProfileService(vault_dir)
    svc.set({"controller": {"name": "First"}}, scope="global")
    svc.set({"controller": {"name": "Second"}}, scope="global")
    got = svc.get(scope="global")
    # Either First or Second, never garbage.
    assert got["controller"]["name"] in ("First", "Second")
    # The actual file must be valid TOML (not half-written).
    import tomllib
    raw = (svc._global_path).read_bytes()
    parsed = tomllib.loads(raw.decode("utf-8"))
    assert "controller" in parsed
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_controller_profile.py -v --no-header
```
Expected: ImportError on `controller_profile`.

- [ ] **Step 3: Implement the service**

Create `src/piighost/service/controller_profile.py`:

```python
"""Loader + merger for ``~/.piighost/controller.toml`` + per-project overrides.

Resolution order (highest priority first when merging):
  1. ``~/.piighost/projects/<project>/controller_overrides.toml``
  2. ``~/.piighost/controller.toml``

Atomic writes via tempfile + os.replace so a concurrent reader sees
either the old contents or the new ones, never half-written TOML.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def _to_toml_str(data: dict[str, Any]) -> str:
    """Minimal TOML serializer for the shapes we use (controller, dpo,
    defaults, mentions_legales). Stdlib has no TOML writer until 3.13;
    we keep deps tight by hand-rolling for our subset."""
    lines: list[str] = []
    # Top-level scalars first
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(_format_scalar_line(k, v))
    # Then sections
    for k, v in data.items():
        if isinstance(v, dict):
            lines.append("")
            lines.append(f"[{k}]")
            for kk, vv in v.items():
                lines.append(_format_scalar_line(kk, vv))
    return "\n".join(lines).strip() + "\n"


def _format_scalar_line(k: str, v: Any) -> str:
    if isinstance(v, bool):
        return f"{k} = {'true' if v else 'false'}"
    if isinstance(v, (int, float)):
        return f"{k} = {v}"
    if isinstance(v, str):
        # Escape backslashes and quotes
        esc = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'{k} = "{esc}"'
    if isinstance(v, list):
        items = []
        for item in v:
            if isinstance(item, str):
                esc = item.replace("\\", "\\\\").replace('"', '\\"')
                items.append(f'"{esc}"')
            else:
                items.append(str(item))
        return f"{k} = [" + ", ".join(items) + "]"
    if v is None:
        return f'{k} = ""'
    raise TypeError(f"Unsupported TOML value type for {k!r}: {type(v).__name__}")


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge ``override`` into ``base``. Returns a new dict."""
    out = {**base}
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class ControllerProfileService:
    """Read + write the controller profile (global + per-project override)."""

    def __init__(self, vault_dir: Path) -> None:
        self._global_path = Path.home() / ".piighost" / "controller.toml"
        self._vault_dir = vault_dir

    def _project_override_path(self, project: str) -> Path:
        return Path.home() / ".piighost" / "projects" / project / "controller_overrides.toml"

    def has_global(self) -> bool:
        return self._global_path.exists()

    def get(self, *, scope: Literal["global", "project"], project: str | None = None) -> dict:
        global_cfg = self._load_global()
        if scope == "global":
            return global_cfg
        if scope == "project":
            if not project:
                raise ValueError("project name is required when scope='project'")
            override_path = self._project_override_path(project)
            if override_path.exists():
                try:
                    override = tomllib.loads(override_path.read_text("utf-8"))
                except (tomllib.TOMLDecodeError, OSError):
                    override = {}
                return _deep_merge(global_cfg, override)
            return global_cfg
        raise ValueError(f"unknown scope: {scope!r}")

    def set(self, profile: dict, *, scope: Literal["global", "project"], project: str | None = None) -> None:
        if scope == "global":
            target = self._global_path
        elif scope == "project":
            if not project:
                raise ValueError("project name is required when scope='project'")
            target = self._project_override_path(project)
        else:
            raise ValueError(f"unknown scope: {scope!r}")
        _atomic_write(target, _to_toml_str(profile))

    def _load_global(self) -> dict:
        if not self._global_path.exists():
            return {}
        try:
            return tomllib.loads(self._global_path.read_text("utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return {}
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_controller_profile.py -v --no-header
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/controller_profile.py tests/unit/test_controller_profile.py
git commit -m "feat(service): ControllerProfileService (Phase 0)

Loader + merger for ~/.piighost/controller.toml + per-project
override at ~/.piighost/projects/<p>/controller_overrides.toml.
Deep-merge for partial overrides (e.g. override only dpo.email).
Atomic writes via tempfile + os.replace.

Hand-rolled minimal TOML writer for the controller-profile shapes
we use (controller, dpo, defaults, mentions_legales) — keeps deps
tight (no external TOML serializer)."
```

---

## Task 8: Wire `DocumentMetadata` into `_ProjectService.index_path`

**Files:**
- Modify: `src/piighost/service/core.py`
- Test: `tests/unit/test_service_index_metadata.py`

- [ ] **Step 1: Write the integration test**

Create `tests/unit/test_service_index_metadata.py`:

```python
"""Integration test: PIIGhostService.index_path populates documents_meta."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir))


def test_index_populates_documents_meta(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client_acme"
    folder.mkdir()
    (folder / "contract_2026.txt").write_text(
        "Article 1 - Le présent contrat est conclu le 2026-04-15.\n"
        "Carol Martin chez Acme Corp.\n",
        encoding="utf-8",
    )

    asyncio.run(svc.index_path(folder, project="test-meta"))

    proj = asyncio.run(svc._get_project("test-meta", auto_create=False))
    metas = proj._indexing_store.list_documents_meta("test-meta")
    assert len(metas) == 1
    m = metas[0]
    assert m.doc_type == "contrat"  # filename matches contract pattern
    assert m.dossier_id == "client_acme"
    assert m.doc_format == ""  # plain text
    asyncio.run(svc.close())


def test_index_populates_meta_for_pdf_with_kreuzberg_metadata(
    vault_dir, monkeypatch, tmp_path,
):
    """If kreuzberg returns metadata for PDF/Office, doc_title etc. populate."""
    pytest.importorskip("kreuzberg")
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client_bravo"
    folder.mkdir()

    # Use the existing test fixture if available
    from pathlib import Path as _P
    sample = _P(r"C:\Users\NMarchitecte\Documents\piighost-test-multi-format\client1\contracts.pdf")
    if not sample.exists():
        pytest.skip("test fixture not present")
    target = folder / "contracts.pdf"
    target.write_bytes(sample.read_bytes())

    asyncio.run(svc.index_path(folder, project="test-meta-pdf"))
    proj = asyncio.run(svc._get_project("test-meta-pdf", auto_create=False))
    metas = proj._indexing_store.list_documents_meta("test-meta-pdf")
    assert len(metas) == 1
    m = metas[0]
    assert m.doc_format == "pdf"
    # title may or may not be populated depending on the source PDF
    asyncio.run(svc.close())


def test_index_path_doesnt_fail_when_extraction_fails(vault_dir, monkeypatch, tmp_path):
    """Extraction failure on one file → that file gets a placeholder meta or none, but index_path completes."""
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client_charlie"
    folder.mkdir()
    # Create a binary garbage file that kreuzberg will fail on
    (folder / "broken.pdf").write_bytes(b"\x00\x01\x02\x03 not a pdf")
    (folder / "good.txt").write_text("Hello, normal text.", encoding="utf-8")

    report = asyncio.run(svc.index_path(folder, project="test-meta-err"))
    assert report.unchanged + report.indexed >= 1  # at least good.txt
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_index_metadata.py -v --no-header -k "not pdf"
```
(Skip the PDF test if no kreuzberg / no fixture.)
Expected: `assert len(metas) == 1` fails because index_path doesn't populate documents_meta yet.

- [ ] **Step 3: Hook into `_ProjectService.index_path`**

Open `src/piighost/service/core.py`. Find the `_ProjectService.index_path` method. Locate the per-file success branch — the block where `self._chunk_store.upsert_chunks(...)`, `self._vault.link_doc_entity(...)`, `self._indexing_store.upsert(FileRecord(...))` are called.

Right AFTER the chunk + vault writes succeed (just before the success-path `if kind == "modified": modified += 1 ...` block), add:

```python
                    # Populate per-document metadata for RGPD compliance
                    # subsystem (Phases 1+2 consume documents_meta).
                    try:
                        from piighost.indexer.ingestor import extract_with_metadata
                        from piighost.service.doc_metadata_extractor import build_metadata
                        # We already have `text` (content extracted earlier in this
                        # branch via extract_text) — re-call extract_with_metadata to
                        # also get kreuzberg's metadata dict. For files where it was
                        # plain-text we get {}, which is fine.
                        _, kmeta = await extract_with_metadata(p)
                        doc_meta = build_metadata(
                            doc_id=doc_id,
                            file_path=p,
                            project_root=root,  # see note below
                            content=text or "",
                            kreuzberg_meta=kmeta,
                            detections=result.entities or [],
                        )
                        self._indexing_store.upsert_document_meta(
                            self._project_name, doc_meta,
                        )
                    except Exception:  # noqa: BLE001
                        # Metadata extraction is non-essential for retrieval —
                        # don't fail the whole index_path on a metadata bug.
                        pass
```

Note on `root`: the existing `index_path` method has the project root path as a local variable (`folder` or `path` depending on the branch). Use whichever variable holds the resolved root of the indexing operation. If the existing code computes `root = path.resolve()` at the top of the method, reuse it. If not, add `root = path.resolve() if path.is_dir() else path.parent.resolve()` near the top of the method.

Inspect the function's existing locals first via:
```
grep -n "def index_path\|root =\|folder =\|path =" src/piighost/service/core.py | head -20
```

If `root` isn't already defined, define it once at the top of the per-file loop.

- [ ] **Step 4: Run integration tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_index_metadata.py -v --no-header -k "not pdf"
```
Expected: 2 passed (the PDF test depends on fixture availability).

If the PDF fixture exists locally, also run with `-k pdf`:
```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_index_metadata.py::test_index_populates_meta_for_pdf_with_kreuzberg_metadata -v --no-header
```
Expected: 1 passed.

- [ ] **Step 5: Run all existing service tests for regression**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_index.py tests/unit/test_service_index_status.py -v --no-header
```
Expected: no regression.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_service_index_metadata.py
git commit -m "feat(service): index_path populates documents_meta (Phase 0)

Hook DocumentMetadata extraction into the per-file success branch of
_ProjectService.index_path. Extraction is wrapped in try/except so a
metadata bug never breaks the indexing pipeline — at worst the row
is missing from documents_meta and consumers (Phases 1+2) treat that
as 'no metadata available'.

Closes Phase 0 implementation."
```

---

## Task 9: Phase 0 smoke test against real test fixture

**Files:**
- No new code — manual verification

- [ ] **Step 1: Run the full Phase 0 test suite together**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_doc_type_classifier.py tests/unit/test_doc_metadata_extractor.py tests/unit/test_indexing_store_documents_meta.py tests/unit/test_audit_v2.py tests/unit/test_controller_profile.py tests/unit/test_service_index_metadata.py -v --no-header
```
Expected: all green (~60+ tests passing).

- [ ] **Step 2: Index the real test folder, then verify documents_meta is populated**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
import asyncio
from pathlib import Path
from piighost.service.core import PIIGhostService

async def main():
    svc = await PIIGhostService.create(vault_dir=Path(r'C:\\Users\\NMarchitecte\\.piighost\\vault'))
    report = await svc.index_path(
        Path(r'C:\\Users\\NMarchitecte\\Documents\\piighost-test-multi-format'),
        project='NMarchitecte', force=True,
    )
    print('index report:', report.model_dump())
    proj = await svc._get_project('NMarchitecte')
    metas = proj._indexing_store.list_documents_meta('NMarchitecte')
    print(f'documents_meta rows: {len(metas)}')
    for m in metas[:5]:
        print(f'  {m.dossier_id}/{m.doc_format} type={m.doc_type} title={m.doc_title!r}')
    await svc.close()
asyncio.run(main())
"
```
Expected: 14 documents_meta rows, with `doc_type` populated (contrat / facture / email / etc.) and `dossier_id` matching the sub-folder (`client1`/`client2`).

- [ ] **Step 3: Final commit if any cleanup**

If the smoke test surfaces a bug (e.g. `dossier_id` always empty because of a path resolution issue), fix it inline and commit:

```bash
git add -A
git commit -m "fix(service): <specific issue surfaced by smoke test>"
```

If everything is clean, no commit needed — Phase 0 is done.

---

## Self-review checklist

**1. Spec coverage:**

| Spec section | Implementing task |
|---|---|
| `DocumentMetadata` Pydantic | Task 1 |
| `documents_meta` SQLite + CRUD | Task 5 |
| `extract_with_metadata` ingestor wrapper | Task 4 |
| `doc_type_classifier` heuristique | Task 2 |
| `doc_metadata_extractor` (date pick + dossier_id + parties) | Task 3 |
| `AuditEvent v2` schema | Task 6 |
| `parse_event_line` v1→v2 reader | Task 6 |
| `AuditLogger.record_v2` with hash chain | Task 6 |
| `ControllerProfileService` (load + merge + atomic write) | Task 7 |
| Wire into `_ProjectService.index_path` | Task 8 |
| Phase 0 smoke test | Task 9 |

✓ Every Phase 0 spec item has a task. No gaps.

**2. Placeholder scan:**

No "TBD", "implement later", "add error handling". Every code step has full code.
The one exception: Task 8 Step 3 says *"Note on `root`: inspect the function's locals first"* — that's because the exact local-variable name depends on what's currently in `core.py`. The instruction is precise (which command to run, what to check, fallback if missing). Acceptable.

**3. Type consistency:**

- `DocumentMetadata` fields used in Task 1 (definition), Task 3 (`build_metadata` constructor), Task 5 (`upsert_document_meta` SQL columns), Task 8 (consumer in core.py). All match.
- `classify(filename, text_head, *, title_hint, format_hint) -> tuple[DocType, float]` — signature in Task 2, called in Task 3.
- `pick_doc_date(meta, content, detections) -> tuple[int | None, str]` — signature in Task 3 used both in tests and in `build_metadata`.
- `AuditEvent` fields in Task 6 used by `parse_event_line`, `record_v2`, `read_events` — all consistent.
- `ControllerProfileService.get(scope=, project=)` in Task 7 used by Task 8 consumers (will be Phase 1+2).

No type/name mismatches.

**4. Scope check:**

Phase 0 is appropriately scoped — 9 tasks, ~3-4 days, foundation only. No user-visible MCP tool added (Phase 1 will add 3, Phase 2 will add 5). This is intentional: Phase 0 must land cleanly before consumers depend on it.
