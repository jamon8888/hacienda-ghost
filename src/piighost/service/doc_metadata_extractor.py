"""Stitch kreuzberg metadata + GLiNER2 detections + heuristics → DocumentMetadata.

Phase 0 — RGPD compliance subsystem (spec §2.1 + §2.2).

Token-scheme decision
---------------------
Parties are stored as deterministic tokens produced by the SAME algorithm as
``LabelHashPlaceholderFactory``:

    token = f"<<{label}:{sha256(text.lower() + ':' + label).hexdigest()[:8]}>>"

This is deliberately identical to the factory so that Phase 1 consumers can
look up vault entries by token without any extra mapping step.

The implementation is inlined here (rather than importing the factory) because:
  1. We operate on raw ``Detection`` objects, not ``Entity`` objects.
  2. Importing and instantiating the factory would require building ``Entity``
     wrappers, which would be more coupling without any benefit.
  3. The algorithm is 2 lines — duplication risk is minimal.

If the factory's default ``hash_length`` (currently 8) ever changes, this
module needs to be updated to stay in sync.  That is documented as a Known
limitation.

Known limitations
-----------------
- ``hash_length`` is hard-coded to 8 to match ``LabelHashPlaceholderFactory``'s
  default.  If the project default changes, parties tokens will diverge from
  vault tokens.
- ``_score_detected_dates`` uses a simple keyword heuristic.  It does not
  parse relative dates ("le lendemain", "hier") or approximate dates ("fin
  avril").
- Raw PII never appears in the output: ``DocumentMetadata`` only contains
  opaque tokens, not the original detection text.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from piighost.models import Detection
from piighost.service.doc_type_classifier import classify
from piighost.service.models import DocumentMetadata

# ---------------------------------------------------------------------------
# Party-label filter — only these labels are considered document parties.
# Dates, amounts, addresses, etc. are NOT parties.
# ---------------------------------------------------------------------------
_PARTY_LABELS: frozenset[str] = frozenset(
    {
        # GLiNER2 French labels
        "nom_personne",
        "prenom",
        "organisation",
        # Common spaCy / transformers labels (kept for forward-compat)
        "PERSON",
        "ORG",
        "PER",
    }
)

# ---------------------------------------------------------------------------
# Date detection — labels that may carry document-relevant date strings
# ---------------------------------------------------------------------------
_DATE_LABELS: frozenset[str] = frozenset(
    {"date", "DATE", "date_naissance", "date_document"}
)

# Keywords that raise a detected date's score as "document date" candidate
_DOC_DATE_KEYWORDS: re.Pattern[str] = re.compile(
    r"\b(fait le|daté du|en date du|le|signé le|établi le|date\s*:)\b",
    re.I,
)

# ---------------------------------------------------------------------------
# ISO 8601 parsing helper
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?$"
)


def _parse_iso_to_epoch(value: Any) -> int | None:
    """Parse an ISO-8601 string to a UTC epoch (int seconds).

    Returns ``None`` on any parse failure, including ``None`` input.

    Handles the trailing ``Z`` timezone designator that Python < 3.11
    ``fromisoformat`` does not accept natively.
    """
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if not _ISO_RE.match(value):
        return None
    # Normalise the Z suffix so fromisoformat works on all Python 3.11+ builds
    # and also on 3.9 / 3.10 where fromisoformat doesn't handle 'Z'.
    normalised = value.replace("Z", "+00:00")
    # Handle compact offset form "2026-04-15T10:00:00+0200" → "+02:00"
    normalised = re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", normalised)
    try:
        dt = datetime.fromisoformat(normalised)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Dossier ID
# ---------------------------------------------------------------------------

def _extract_dossier_id(file_path: Path, project_root: Path) -> str:
    """Return the first sub-folder name under *project_root* for *file_path*.

    If the file sits directly inside *project_root* (no subfolder), returns
    an empty string.

    Examples::

        _extract_dossier_id(root/"client_acme"/"contracts"/"foo.pdf", root)
        # → "client_acme"

        _extract_dossier_id(root/"foo.pdf", root)
        # → ""
    """
    try:
        rel = file_path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return ""
    parts = rel.parts
    # parts[0] would be the filename if directly under root (len == 1)
    if len(parts) <= 1:
        return ""
    return parts[0]


# ---------------------------------------------------------------------------
# Date picking
# ---------------------------------------------------------------------------

def _score_detected_dates(
    content: str, detections: list[Detection]
) -> list[tuple[int, int]]:
    """Return ``(epoch, score)`` pairs for date detections, scored by context.

    A date gets a higher score when it appears close to keywords like
    "fait le" or "daté du" in the surrounding text.  Only dates whose
    raw text can be parsed by ``_parse_iso_to_epoch`` are included.
    """
    results: list[tuple[int, int]] = []
    for d in detections:
        if d.label not in _DATE_LABELS:
            continue
        epoch = _parse_iso_to_epoch(d.text)
        if epoch is None:
            continue
        # Grab a context window of 80 chars before the detection
        window_start = max(0, d.position.start_pos - 80)
        window = content[window_start : d.position.start_pos]
        score = 2 if _DOC_DATE_KEYWORDS.search(window) else 1
        results.append((epoch, score))
    return results


def pick_doc_date(
    kreuzberg_meta: dict[str, Any],
    content: str,
    detections: list[Detection],
) -> tuple[int | None, str]:
    """Return ``(epoch_or_None, source_label)``.

    Priority order:
    1. ``kreuzberg_meta["created_at"]`` → source ``"kreuzberg_creation"``
    2. ``kreuzberg_meta["modified_at"]`` → source ``"kreuzberg_modified"``
    3. Highest-scored detected date token → source ``"heuristic_detected"``
    4. Nothing parseable → ``(None, "none")``
    """
    created = _parse_iso_to_epoch(kreuzberg_meta.get("created_at"))
    if created is not None:
        return created, "kreuzberg_creation"

    modified = _parse_iso_to_epoch(kreuzberg_meta.get("modified_at"))
    if modified is not None:
        return modified, "kreuzberg_modified"

    scored = _score_detected_dates(content, detections)
    if scored:
        best_epoch, _ = max(scored, key=lambda t: t[1])
        return best_epoch, "heuristic_detected"

    return None, "none"


# ---------------------------------------------------------------------------
# Party token computation (mirrors LabelHashPlaceholderFactory exactly)
# ---------------------------------------------------------------------------

def _party_token(text: str, label: str, hash_length: int = 8) -> str:
    """Compute the same token that ``LabelHashPlaceholderFactory`` would emit.

    Algorithm: ``sha256(f"{text.lower()}:{label}".encode()).hexdigest()[:8]``
    wrapped in ``<<label:digest>>``.

    Raw PII (``text``) is hashed and NEVER returned as-is; the returned
    token is safe for outbound metadata.
    """
    raw = f"{text.lower()}:{label}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:hash_length]
    return f"<<{label}:{digest}>>"


def _anonymise_authors(authors: list[str] | None) -> list[str]:
    """Replace raw author names with deterministic placeholder tokens.

    kreuzberg returns the raw 'authors' field from PDF/Office metadata.
    Storing those names as-is in ``documents_meta`` would leak through
    the Phase 2 processing_register. Each non-blank author becomes
    ``<<author:HASH8>>`` (sha256 of label+text, same scheme as
    LabelHashPlaceholderFactory).

    Empty / None / whitespace-only inputs are filtered out.
    Duplicates are deduplicated while preserving first-seen order.
    """
    if not authors:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in authors:
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if not text:
            continue
        token = _party_token(text, "author")
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_metadata(
    *,
    doc_id: str,
    file_path: Path,
    project_root: Path,
    content: str,
    kreuzberg_meta: dict[str, Any],
    detections: list[Detection],
    entity_refs: list | None = None,
) -> DocumentMetadata:
    """Stitch all available signals into one ``DocumentMetadata``.

    Parameters
    ----------
    doc_id:
        Stable document identifier (typically SHA-256 of file content).
    file_path:
        Absolute path to the source file.
    project_root:
        Absolute path to the project root (used to compute ``dossier_id``).
    content:
        Full extracted text (may be empty for encrypted / binary files).
    kreuzberg_meta:
        Free metadata dict returned by kreuzberg (flat, not nested).
        Expected keys (all optional): ``title``, ``subject``, ``authors``,
        ``language``, ``page_count``, ``format_type``, ``created_at``,
        ``modified_at``, ``is_encrypted``.
    detections:
        GLiNER2 (or other) ``Detection`` objects for the document.
        Used for date picking and party extraction.
        Raw PII is never written to the output — only opaque tokens.

    Notes on parties
    ----------------
    ``parties`` contains deterministic tokens of the form
    ``<<label:sha256hex8>>`` computed from ``(detection.text, detection.label)``
    — the same scheme as ``LabelHashPlaceholderFactory``.  Phase 1 consumers
    (subject_clustering, RGPD audit) can look these tokens up directly in the
    vault without any extra mapping.  Only detections whose label belongs to
    ``_PARTY_LABELS`` are included; duplicates (same token) are de-duplicated
    while preserving first-occurrence order.
    """
    # 1. Classify document type
    doc_type, doc_type_confidence = classify(
        filename=file_path.name,
        text_head=content,
        title_hint=kreuzberg_meta.get("title"),
        format_hint=kreuzberg_meta.get("format_type"),
    )

    # 2. Pick document date
    doc_date, doc_date_source = pick_doc_date(kreuzberg_meta, content, detections)

    # 3. Extract dossier_id
    dossier_id = _extract_dossier_id(file_path, project_root)

    # 4. Build parties list — opaque tokens only, raw PII never leaves this fn.
    #
    # Two input shapes are supported:
    #   - ``detections`` (list of ``Detection``): raw NER output. We hash
    #     ``(text, label)`` to derive the party token. Used when the caller
    #     has the pre-anonymized stream.
    #   - ``entity_refs`` (list of EntityRef-like with ``.token`` + ``.label``):
    #     post-anonymize references where the token has already been computed
    #     by ``LabelHashPlaceholderFactory``. We use the token directly without
    #     re-hashing (saves work; both schemes produce identical output).
    #
    # The indexer pipeline calls ``anonymize()`` first (entity_refs available),
    # so passing them avoids a redundant detect call. ``detections`` is
    # preserved for callers that still have raw Detection objects (tests,
    # future extension points).
    seen_tokens: set[str] = set()
    parties: list[str] = []
    for d in detections:
        if d.label not in _PARTY_LABELS:
            continue
        token = _party_token(d.text, d.label)
        if token not in seen_tokens:
            seen_tokens.add(token)
            parties.append(token)
    for ref in entity_refs or ():
        label = getattr(ref, "label", None)
        if label not in _PARTY_LABELS:
            continue
        token = getattr(ref, "token", None)
        if not token or token in seen_tokens:
            continue
        seen_tokens.add(token)
        parties.append(token)

    # 5. Assemble DocumentMetadata
    authors_raw = kreuzberg_meta.get("authors")
    raw_authors: list[str] = (
        authors_raw if isinstance(authors_raw, list) else
        [authors_raw] if isinstance(authors_raw, str) and authors_raw else
        []
    )
    authors = _anonymise_authors(raw_authors)

    return DocumentMetadata(
        doc_id=doc_id,
        doc_type=doc_type,
        doc_type_confidence=doc_type_confidence,
        doc_date=doc_date,
        doc_date_source=doc_date_source,
        doc_title=kreuzberg_meta.get("title") or None,
        doc_subject=kreuzberg_meta.get("subject") or None,
        doc_authors=authors,
        doc_language=kreuzberg_meta.get("language") or None,
        doc_page_count=kreuzberg_meta.get("page_count") or None,
        doc_format=kreuzberg_meta.get("format_type") or "",
        is_encrypted_source=bool(kreuzberg_meta.get("is_encrypted", False)),
        parties=parties,
        dossier_id=dossier_id,
        extracted_at=int(time.time()),
    )
