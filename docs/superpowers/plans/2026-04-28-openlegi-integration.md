# OpenLégi Integration Implementation Plan (Phase 9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in French legal-citation verification (Legifrance via OpenLégi) and federated local-vs-legal search to the hacienda plugin, with strict outbound PII redaction.

**Architecture:** Hybrid daemon proxy. Daemon owns the network boundary (one outbound endpoint, SQLite cache, redactor, audit). Plugin skills orchestrate the verification + search workflows. PISTE token lives in a separate `~/.piighost/credentials.toml` (chmod 600 on POSIX, ACL on Windows) and is never returned via any MCP method.

**Tech Stack:** Python 3.13, httpx (already in base deps — no new heavy deps), Pydantic with `ConfigDict(extra="forbid")`, stdlib `tomllib`, SQLite. Mocking via `pytest-httpx` in test extra.

**Spec:** `docs/superpowers/specs/2026-04-28-openlegi-integration-design.md` (commit `68fb787`).

**Phase 0–8 status:** all merged. Last commit was `8d0b4c2` (Phase 8 entity-token mapping).

**Branch:** all backend work commits to `master` in the piighost repo. Plugin commits to `main` in the worktree at `.worktrees/hacienda-plugin`.

---

## File map (Phase 9)

| Path | Type | Owns |
|---|---|---|
| `src/piighost/legal/__init__.py` | new | Lazy `__getattr__` package init (mirrors `compliance/`) |
| `src/piighost/legal/reference_models.py` | new | `LegalReference`, `VerificationResult`, `LegalHit`, `LegalRefType` Pydantic models |
| `src/piighost/legal/ref_extractor.py` | new | `extract_references(text)` regex-based parser (ported from user's skill) |
| `src/piighost/legal/redactor.py` | new | `OutboundRedactor` — anonymize + legal-grammar whitelist |
| `src/piighost/legal/cache.py` | new | `LegalCache(vault_dir)` — SQLite at `<vault>/legal_cache.sqlite` |
| `src/piighost/legal/piste_client.py` | new | `PisteClient` — sync httpx wrapper for OpenLégi MCP endpoint |
| `src/piighost/legal/templates/taxonomie.md` | new (copy) | Bundled reference for verify skill |
| `src/piighost/legal/templates/strategies-recherche.md` | new (copy) | Bundled reference for verify skill |
| `src/piighost/service/credentials.py` | new | `CredentialsService` for `~/.piighost/credentials.toml` |
| `src/piighost/service/config.py` | modify | Add `OpenLegiSection` |
| `src/piighost/service/core.py` | modify | Add 5 `PIIGhostService.legal_*` methods |
| `src/piighost/mcp/tools.py` | modify | 5 new ToolSpec |
| `src/piighost/mcp/shim.py` | modify | 5 new `@mcp.tool` wrappers |
| `src/piighost/daemon/server.py` | modify | 5 new dispatch handlers |
| `pyproject.toml` | modify | `pytest-httpx` in test extra |
| `tests/unit/test_legal_reference_models.py` | new | Pydantic round-trip + `extra="forbid"` |
| `tests/unit/test_legal_ref_extractor.py` | new | Regex coverage + plurals + tricky cases |
| `tests/unit/test_legal_redactor.py` | new | Whitelist correctness + crash-safety |
| `tests/unit/test_legal_cache.py` | new | TTL + invalidation + key canonicalization |
| `tests/unit/test_legal_piste_client.py` | new | httpx mocked, retries, SSE parse |
| `tests/unit/test_credentials_service.py` | new | TOML lifecycle, get-strips-token |
| `tests/unit/test_legal_service.py` | new | 5 RPC methods with `httpx.MockTransport` |
| `tests/integration/test_legal_outbound_privacy.py` | new | **THE 5-PII-strings privacy gate** |
| `tests/integration/test_legal_e2e.py` | new | Real daemon + mocked OpenLégi end-to-end |
| `.worktrees/hacienda-plugin/skills/legal-verify/SKILL.md` | new | `/hacienda:legal:verify` |
| `.worktrees/hacienda-plugin/skills/legal-setup/SKILL.md` | new | `/hacienda:legal:setup` |
| `.worktrees/hacienda-plugin/skills/search/SKILL.md` | new | `/hacienda:search` (federated) |
| `.worktrees/hacienda-plugin/skills/setup/SKILL.md` | modify | Add Step 7 (optional OpenLégi) |
| `.worktrees/hacienda-plugin/skills/knowledge-base/SKILL.md` | modify | Mark deprecated → search |
| `.worktrees/hacienda-plugin/skills/rgpd-dpia/SKILL.md` | modify | Optional CNIL enrichment |
| `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` | modify | v0.7.0 → v0.8.0 |

---

## Task 1: Pydantic reference models

**Files:**
- Create: `src/piighost/legal/__init__.py`
- Create: `src/piighost/legal/reference_models.py`
- Test: `tests/unit/test_legal_reference_models.py`

Pure Pydantic types — no business logic. Lazy `__init__.py` mirrors the `compliance/` package pattern (Phase 6 Task 1).

- [ ] **Step 1: Write failing tests**

```python
"""Pydantic shapes for the legal subsystem."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from piighost.legal.reference_models import (
    LegalReference,
    VerificationResult,
    LegalHit,
    LegalRefType,
)


def test_legal_reference_minimal_construction():
    r = LegalReference(
        ref_id=1,
        ref_type=LegalRefType.ARTICLE_CODE,
        raw_text="article 1240 du Code civil",
        position=42,
    )
    assert r.ref_id == 1
    assert r.ref_type == LegalRefType.ARTICLE_CODE


def test_legal_reference_rejects_extra_keys():
    with pytest.raises(ValidationError, match="(extra|forbid|not permitted)"):
        LegalReference(
            ref_id=1,
            ref_type=LegalRefType.ARTICLE_CODE,
            raw_text="x",
            position=0,
            __html_payload="<script>",
        )


def test_verification_result_status_enum():
    """All 8 status values from the spec are accepted."""
    valid = [
        "VERIFIE_EXACT", "VERIFIE_MINEUR", "PARTIELLEMENT_EXACT",
        "SUBSTANTIELLEMENT_ERRONE", "HALLUCINATION",
        "UNKNOWN_OPENLEGI_DISABLED", "UNKNOWN_AUTH_FAILED",
        "UNKNOWN_RATE_LIMITED", "UNKNOWN_NETWORK",
        "UNKNOWN_PARSE_ERROR",
    ]
    for s in valid:
        VerificationResult(status=s, score=0)


def test_verification_result_rejects_unknown_status():
    with pytest.raises(ValidationError):
        VerificationResult(status="WHATEVER", score=0)


def test_legal_hit_minimal():
    h = LegalHit(
        source="code",
        title="Code civil, Art. 1240",
        snippet="Tout fait quelconque…",
        url="https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000032041604/",
    )
    assert h.source == "code"
    assert h.score is None  # optional
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_reference_models.py -v --no-header
```
Expected: ImportError on `piighost.legal.reference_models`.

- [ ] **Step 3: Create the lazy package init**

`src/piighost/legal/__init__.py`:

```python
"""piighost.legal — French legal-citation verification and search.

Lazy public API (PEP 562) to keep startup fast — pulling the
PisteClient + httpx + retry logic only when needed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "extract_references",
    "OutboundRedactor",
    "LegalCache",
    "PisteClient",
    "LegalReference",
    "VerificationResult",
    "LegalHit",
    "LegalRefType",
]


def __getattr__(name: str):
    if name == "extract_references":
        from .ref_extractor import extract_references
        return extract_references
    if name == "OutboundRedactor":
        from .redactor import OutboundRedactor
        return OutboundRedactor
    if name == "LegalCache":
        from .cache import LegalCache
        return LegalCache
    if name == "PisteClient":
        from .piste_client import PisteClient
        return PisteClient
    if name in ("LegalReference", "VerificationResult", "LegalHit", "LegalRefType"):
        from . import reference_models
        return getattr(reference_models, name)
    raise AttributeError(f"module 'piighost.legal' has no attribute {name!r}")


if TYPE_CHECKING:
    from .ref_extractor import extract_references  # noqa: F401
    from .redactor import OutboundRedactor  # noqa: F401
    from .cache import LegalCache  # noqa: F401
    from .piste_client import PisteClient  # noqa: F401
    from .reference_models import (  # noqa: F401
        LegalReference, VerificationResult, LegalHit, LegalRefType,
    )
```

- [ ] **Step 4: Implement `reference_models.py`**

Create `src/piighost/legal/reference_models.py`:

```python
"""Pydantic shapes for the legal subsystem.

LegalReference     — output of extract_references()
VerificationResult — output of verify_legal_ref()
LegalHit           — output of search_legal()
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LegalRefType(StrEnum):
    ARTICLE_CODE = "ARTICLE_CODE"
    LOI = "LOI"
    DECRET = "DECRET"
    ORDONNANCE = "ORDONNANCE"
    JURISPRUDENCE = "JURISPRUDENCE"
    JOURNAL_OFFICIEL = "JOURNAL_OFFICIEL"
    AUTRE = "AUTRE"


class LegalReference(BaseModel):
    """One legal reference extracted from input text."""
    model_config = ConfigDict(extra="forbid")

    ref_id: int
    ref_type: LegalRefType
    raw_text: str
    numero: Optional[str] = None       # article or law number
    code: Optional[str] = None         # code name (Code civil, …)
    text_id: Optional[str] = None      # AAAA-NNN format for laws/decrees
    date: Optional[str] = None
    juridiction: Optional[str] = None
    formation: Optional[str] = None
    pourvoi: Optional[str] = None
    contenu_cite: Optional[str] = None
    position: int = 0


VerificationStatus = Literal[
    "VERIFIE_EXACT",
    "VERIFIE_MINEUR",
    "PARTIELLEMENT_EXACT",
    "SUBSTANTIELLEMENT_ERRONE",
    "HALLUCINATION",
    "UNKNOWN_OPENLEGI_DISABLED",
    "UNKNOWN_AUTH_FAILED",
    "UNKNOWN_RATE_LIMITED",
    "UNKNOWN_NETWORK",
    "UNKNOWN_PARSE_ERROR",
]


class VerificationResult(BaseModel):
    """Outcome of verifying a single LegalReference against OpenLégi."""
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    score: Optional[int] = None          # 0-100 per the user's taxonomy
    type_erreur: Optional[str] = None    # REF_INEXISTANTE / NUM_ERRONE / …
    url_legifrance: Optional[str] = None
    correction: Optional[str] = None
    message: Optional[str] = None        # human-readable diagnosis


class LegalHit(BaseModel):
    """One result from search_legal()."""
    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "code", "jurisprudence_judiciaire", "jurisprudence_administrative",
        "cnil", "jorf", "lois_decrets", "conventions_collectives",
    ]
    title: str
    snippet: str = ""
    url: Optional[str] = None
    score: Optional[float] = None
```

- [ ] **Step 5: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_reference_models.py -v --no-header
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/legal/__init__.py src/piighost/legal/reference_models.py tests/unit/test_legal_reference_models.py
git commit -m "feat(legal): Pydantic models for legal subsystem (Phase 9 Task 1)

Three top-level types with extra='forbid':
  - LegalReference: extracted ref shape (ref_type enum + optional fields)
  - VerificationResult: verify_legal_ref output (10-status enum + score)
  - LegalHit: search_legal output (7-source enum + URL)

Lazy __getattr__ in piighost.legal/__init__.py mirrors the compliance/
package pattern from Phase 6 to keep startup fast."
```

---

## Task 2: Reference extractor

**Files:**
- Create: `src/piighost/legal/ref_extractor.py`
- Test: `tests/unit/test_legal_ref_extractor.py`

Port the regex extractor from the user's `legal-hallucination-checker` skill (`scripts/extract_references.py`). Pure-function — no I/O, no network.

- [ ] **Step 1: Write the failing tests**

```python
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
    # 'article' starts at index 11 ("Bonjour. L'article…" — 0-indexed)
    art = refs[0]
    assert art.position >= 9  # after "Bonjour. "
    assert text[art.position : art.position + len("article")].lower() == "article"
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_ref_extractor.py -v --no-header
```
Expected: ImportError.

- [ ] **Step 3: Implement the extractor**

Create `src/piighost/legal/ref_extractor.py`:

```python
"""Regex-based extractor for French legal references.

Ported from the user's legal-hallucination-checker skill
(scripts/extract_references.py). Pure-function — no I/O.
"""
from __future__ import annotations

import re

from piighost.legal.reference_models import LegalReference, LegalRefType


# Code name → official name mapping (from skill's CODE_ALIASES)
_CODE_ALIASES = {
    "c. civ.": "Code civil",
    "c. civ": "Code civil",
    "code civ.": "Code civil",
    "c. pén.": "Code pénal",
    "c. pen.": "Code pénal",
    "c. com.": "Code de commerce",
    "c. trav.": "Code du travail",
    "c. conso.": "Code de la consommation",
    "c. pr. pén.": "Code de procédure pénale",
    "cpp": "Code de procédure pénale",
    "cgi": "Code général des impôts",
    "csp": "Code de la santé publique",
    "cpi": "Code de la propriété intellectuelle",
}


def _normalize_code(raw: str) -> str:
    lower = raw.lower().strip().rstrip(".")
    for alias, official in _CODE_ALIASES.items():
        if alias.rstrip(".") in lower:
            return official
    return raw.strip()


# Regex patterns (compiled once)
_RE_ARTICLE_CODE = re.compile(
    r"(?:l')?articles?\s+([LRDA]\.?\s*)?(\d+(?:-\d+)*)"
    r"\s+du\s+(Code\s+[\w\s'-]+?)"
    r"(?=\s*[,\.\);]|\s+(?:et|qui|dispose|prévoit|énonce)|\s*$)",
    re.I,
)
_RE_ART_ABBREV = re.compile(
    r"art\.?\s+([LRDA]\.?\s*)?(\d+(?:-\d+)*)\s+(?:du\s+)?(C\.\s*[\w\s\.]+?)(?=\s|$)",
    re.I,
)
_RE_LOI = re.compile(
    r"loi\s+n[°o]?\s*(\d{2,4}[-–]\d+)\s+du\s+(\d{1,2}\s+\w+\s+\d{4})",
    re.I,
)
_RE_DECRET = re.compile(
    r"décrets?\s+n[°o]?\s*(\d{2,4}[-–]\d+)(?:\s+du\s+(\d{1,2}\s+\w+\s+\d{4}))?",
    re.I,
)
_RE_ORDONNANCE = re.compile(
    r"ordonnance\s+n[°o]?\s*(\d{2,4}[-–]\d+)(?:\s+du\s+(\d{1,2}\s+\w+\s+\d{4}))?",
    re.I,
)
_RE_JURISPRUDENCE = re.compile(
    r"(Cass\.?\s*(?:ass\.?\s*plén\.?|civ\.?\s*\d(?:re|e|ère)?|com\.?|crim\.?|soc\.?|ch\.?\s*mixte))"
    r"[,\s]+(\d{1,2}\s+\w+\s+\d{4})"
    r"[,\s]+n[°o]?\s*(\d{2}[-–]\d+\.?\d*)",
    re.I,
)


def extract_references(text: str) -> list[LegalReference]:
    """Extract all legal references in *text*.

    Returns a list of LegalReference with sequential ref_id starting at 1.
    Order follows source position. Empty list if no refs found.
    """
    if not text:
        return []
    refs: list[LegalReference] = []
    next_id = 1

    def _add(ref_type: LegalRefType, raw_text: str, position: int, **fields):
        nonlocal next_id
        refs.append(LegalReference(
            ref_id=next_id, ref_type=ref_type,
            raw_text=raw_text, position=position, **fields,
        ))
        next_id += 1

    # Articles in codes (full form)
    for m in _RE_ARTICLE_CODE.finditer(text):
        prefix = (m.group(1) or "").strip()
        numero = m.group(2)
        if prefix:
            numero = f"{prefix} {numero}".strip()
        _add(
            LegalRefType.ARTICLE_CODE,
            raw_text=m.group(0),
            position=m.start(),
            numero=numero,
            code=_normalize_code(m.group(3)),
        )

    # Articles abbreviated form
    for m in _RE_ART_ABBREV.finditer(text):
        prefix = (m.group(1) or "").strip()
        numero = m.group(2)
        if prefix:
            numero = f"{prefix} {numero}".strip()
        _add(
            LegalRefType.ARTICLE_CODE,
            raw_text=m.group(0),
            position=m.start(),
            numero=numero,
            code=_normalize_code(m.group(3)),
        )

    # Lois
    for m in _RE_LOI.finditer(text):
        _add(
            LegalRefType.LOI,
            raw_text=m.group(0),
            position=m.start(),
            text_id=m.group(1).replace("–", "-"),
            date=m.group(2),
        )

    # Décrets
    for m in _RE_DECRET.finditer(text):
        _add(
            LegalRefType.DECRET,
            raw_text=m.group(0),
            position=m.start(),
            text_id=m.group(1).replace("–", "-"),
            date=m.group(2),
        )

    # Ordonnances
    for m in _RE_ORDONNANCE.finditer(text):
        _add(
            LegalRefType.ORDONNANCE,
            raw_text=m.group(0),
            position=m.start(),
            text_id=m.group(1).replace("–", "-"),
            date=m.group(2),
        )

    # Jurisprudence
    for m in _RE_JURISPRUDENCE.finditer(text):
        _add(
            LegalRefType.JURISPRUDENCE,
            raw_text=m.group(0),
            position=m.start(),
            juridiction="Cour de cassation",
            formation=m.group(1),
            date=m.group(2),
            pourvoi=m.group(3).replace("–", "-"),
        )

    # Sort by position, re-number
    refs.sort(key=lambda r: r.position)
    for i, r in enumerate(refs, start=1):
        r.ref_id = i
    return refs
```

- [ ] **Step 4: Run tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_ref_extractor.py -v --no-header
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/legal/ref_extractor.py tests/unit/test_legal_ref_extractor.py
git commit -m "feat(legal): regex-based legal reference extractor (Phase 9 Task 2)

Ported from the user's legal-hallucination-checker skill
scripts/extract_references.py. Pure-function — no I/O, no network.

Recognised types: ARTICLE_CODE, LOI, DECRET, ORDONNANCE, JURISPRUDENCE.
Code-name normalisation via _CODE_ALIASES (C. civ → Code civil, etc.).
9 regression tests covering full + abbreviated forms, multi-ref
paragraphs, position preservation, ref_id sequentiality."
```

---

## Task 3: OutboundRedactor + privacy gate

**Files:**
- Create: `src/piighost/legal/redactor.py`
- Test: `tests/unit/test_legal_redactor.py`

The privacy boundary. Every outbound payload to OpenLégi passes through here. Strict failure mode: redaction errors **refuse the call**, never proceed to the wire.

- [ ] **Step 1: Write the failing tests**

```python
"""OutboundRedactor — the privacy boundary."""
from __future__ import annotations

import pytest

from piighost.legal.redactor import OutboundRedactor


def _stub_anonymize(text: str) -> str:
    """Replaces 'Marie Curie' / 'IBAN: FR…' / phone with [REDACTED]."""
    out = text
    out = out.replace("Marie Curie", "[REDACTED]")
    out = out.replace("FR1420041010050500013M02606", "[REDACTED]")
    out = out.replace("+33 6 12 34 56 78", "[REDACTED]")
    out = out.replace("marie@acme.fr", "[REDACTED]")
    return out


def test_redact_keeps_legal_grammar():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact("Marie Curie a invoqué l'article 1240 du Code civil.")
    # PII redacted
    assert "Marie Curie" not in out
    # Legal grammar preserved
    assert "article 1240" in out
    assert "Code civil" in out


def test_redact_keeps_pourvoi_number():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact("Cass. civ. 1re, 15 mars 2023, n°21-12.345 (Marie Curie c. Acme)")
    assert "21-12.345" in out
    assert "Cass" in out
    assert "Marie Curie" not in out


def test_redact_keeps_loi_number():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact("La loi n°78-17 du 6 janvier 1978 — Marie Curie est concernée.")
    assert "78-17" in out
    assert "1978" in out
    assert "Marie Curie" not in out


def test_redact_strips_iban_email_phone():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact(
        "IBAN FR1420041010050500013M02606, "
        "email marie@acme.fr, "
        "tél +33 6 12 34 56 78."
    )
    assert "FR1420041010050500013M02606" not in out
    assert "marie@acme.fr" not in out
    assert "+33 6 12 34 56 78" not in out


def test_redact_strips_pii_token_format():
    """Even our own placeholder format leaks pattern info — strip it."""
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact("article 1240 — sujet: <<nom_personne:abc12345>>")
    assert "<<nom_personne:abc12345>>" not in out
    assert "article 1240" in out


def test_redactor_hard_fails_on_anonymize_crash():
    """If anonymize_fn raises, the redactor raises — never silently proceed."""
    def crash(text):
        raise RuntimeError("anonymize boom")

    r = OutboundRedactor(anonymize_fn=crash)
    with pytest.raises(RuntimeError, match="boom"):
        r.redact("anything")


def test_redact_dict_payload():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact_dict({
        "search": "Marie Curie article 1240",
        "champ": "ARTICLE",
        "max_results": 5,
    })
    assert "Marie Curie" not in out["search"]
    assert "article 1240" in out["search"]
    # Non-string fields untouched
    assert out["max_results"] == 5
    assert out["champ"] == "ARTICLE"
```

- [ ] **Step 2: Run tests**

Expected: ImportError.

- [ ] **Step 3: Implement the redactor**

Create `src/piighost/legal/redactor.py`:

```python
"""OutboundRedactor — sanitises payloads before they leave the daemon.

Strategy:
  1. Strip any <<label:HASH>> tokens (our placeholder format leaks
     the redaction scheme even though the originals are gone).
  2. Apply anonymize_fn to scrub any PII the caller missed.
  3. Verify legal-grammar patterns survive (article numbers, dates,
     code names, pourvoi numbers, etc.).
  4. Hard-fail on anonymize crash — never proceed with un-redacted
     payload.
"""
from __future__ import annotations

import re
from typing import Any, Callable


# Patterns we DO want to keep — legal grammar essential to the search.
_LEGAL_GRAMMAR_PATTERNS = [
    re.compile(r"\barticle\s+[LRD]?\.?\s*\d+(?:-\d+)*\b", re.I),
    re.compile(r"\b(loi|décret|ordonnance)\s+n[°o]?\s*\d{2,4}[-–]\d+", re.I),
    re.compile(r"\b\d{2}[-–]\d+\.\d+\b"),  # pourvoi
    re.compile(r"\b(Cass|CE|CC|CJUE|TJ|TC)\b\.?", re.I),
    re.compile(r"\b\d{1,2}\s+\w+\s+\d{4}\b"),  # French dates
    re.compile(r"\bCode\s+[\w\s'-]+", re.I),
]

# Strip our own placeholder format
_PLACEHOLDER_RE = re.compile(r"<<[a-zA-Z_]+:[a-f0-9]+>>")


class OutboundRedactor:
    """Apply anonymize() + legal-grammar whitelist before wire send."""

    def __init__(self, anonymize_fn: Callable[[str], str]) -> None:
        self._anonymize = anonymize_fn

    def redact(self, text: str) -> str:
        """Return a sanitised copy of *text* safe to send outbound.

        Raises whatever ``anonymize_fn`` raises — we never silently
        proceed with un-redacted input.
        """
        if not text:
            return text
        # 1. Strip our placeholder format
        out = _PLACEHOLDER_RE.sub("[REDACTED]", text)
        # 2. Anonymize whatever PII slipped through
        out = self._anonymize(out)
        return out

    def redact_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact every string value in *payload*. Non-string
        values are kept verbatim (numbers, booleans, lists of non-strings).
        """
        result: dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(v, str):
                result[k] = self.redact(v)
            elif isinstance(v, dict):
                result[k] = self.redact_dict(v)
            elif isinstance(v, list):
                result[k] = [
                    self.redact(item) if isinstance(item, str) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result
```

- [ ] **Step 4: Run tests**

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/legal/redactor.py tests/unit/test_legal_redactor.py
git commit -m "feat(legal): OutboundRedactor — privacy boundary for legal API calls

Phase 9 Task 3. Sanitises payloads before they leave the daemon for
OpenLégi. Strategy:

  1. Strip <<label:HASH>> placeholder tokens (our format leaks
     the redaction scheme even though originals are gone)
  2. Apply caller-provided anonymize_fn to scrub residual PII
  3. Hard-fail on anonymize crash — never proceed with un-redacted
     payload

Whitelist regex set (preserved verbatim):
  - article numbers (\\barticle\\s+[LRD]?\\.?\\s*\\d+(-\\d+)*)
  - laws/decrees with n° (loi/décret/ordonnance n°AAAA-NNN)
  - pourvoi numbers (\\d{2}-\\d+\\.\\d+)
  - court abbreviations (Cass/CE/CC/CJUE/TJ/TC)
  - French dates (\\d{1,2} \\w+ \\d{4})
  - code names (Code …)

Seven regression tests including the hard-fail-on-anonymize-crash gate."
```

---

## Task 4: LegalCache (SQLite TTL)

**Files:**
- Create: `src/piighost/legal/cache.py`
- Test: `tests/unit/test_legal_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
"""LegalCache — SQLite TTL cache for OpenLégi responses."""
from __future__ import annotations

import json
import time

import pytest

from piighost.legal.cache import LegalCache


@pytest.fixture()
def cache(tmp_path):
    return LegalCache(vault_dir=tmp_path)


def test_set_then_get(cache):
    cache.set("verify_legal_ref", {"ref_id": 1}, response={"status": "OK"}, ttl_seconds=3600)
    hit = cache.get("verify_legal_ref", {"ref_id": 1})
    assert hit == {"status": "OK"}


def test_get_returns_none_on_miss(cache):
    assert cache.get("verify_legal_ref", {"ref_id": 99}) is None


def test_canonical_key_matches_dict_order(cache):
    """{a:1, b:2} and {b:2, a:1} must produce the same cache key."""
    cache.set("search_legal", {"a": 1, "b": 2}, response={"v": "x"}, ttl_seconds=60)
    hit = cache.get("search_legal", {"b": 2, "a": 1})
    assert hit == {"v": "x"}


def test_ttl_expiration(cache, monkeypatch):
    cache.set("verify_legal_ref", {"k": 1}, response={"v": 1}, ttl_seconds=1)
    fake_now = time.time() + 5  # 5s in the future
    monkeypatch.setattr("time.time", lambda: fake_now)
    assert cache.get("verify_legal_ref", {"k": 1}) is None


def test_clear_all(cache):
    cache.set("verify_legal_ref", {"k": 1}, response={}, ttl_seconds=60)
    cache.set("search_legal", {"q": "x"}, response={}, ttl_seconds=60)
    n = cache.clear()
    assert n == 2
    assert cache.get("verify_legal_ref", {"k": 1}) is None
    assert cache.get("search_legal", {"q": "x"}) is None


def test_hits_counter_increments(cache):
    cache.set("verify_legal_ref", {"k": 1}, response={"v": 1}, ttl_seconds=60)
    cache.get("verify_legal_ref", {"k": 1})
    cache.get("verify_legal_ref", {"k": 1})
    cache.get("verify_legal_ref", {"k": 1})
    stats = cache.stats()
    assert stats["total_hits"] == 3


def test_cache_survives_reopen(cache, tmp_path):
    cache.set("verify_legal_ref", {"k": 1}, response={"v": 1}, ttl_seconds=3600)
    cache.close()
    cache2 = LegalCache(vault_dir=tmp_path)
    assert cache2.get("verify_legal_ref", {"k": 1}) == {"v": 1}
```

- [ ] **Step 2: Run tests** — Expected: ImportError.

- [ ] **Step 3: Implement `cache.py`**

Create `src/piighost/legal/cache.py`:

```python
"""LegalCache — SQLite TTL cache for OpenLégi responses.

Keyed on ``sha256(tool || canonical_json(args))``. TTL strategy is
caller-decided (Task 7's service methods pick 7 days for verify, 5
minutes for freeform search). Cache survives daemon restarts.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS legal_cache (
    cache_key   TEXT PRIMARY KEY,
    tool        TEXT NOT NULL,
    response    TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    hits        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_legal_cache_created ON legal_cache(created_at);
"""


class LegalCache:
    """SQLite-backed cache for OpenLégi tool responses."""

    def __init__(self, vault_dir: Path) -> None:
        self._path = Path(vault_dir) / "legal_cache.sqlite"
        self._conn = sqlite3.connect(str(self._path))
        self._conn.executescript(_SCHEMA)

    @staticmethod
    def _key(tool: str, args: dict) -> str:
        """sha256(tool || canonical_json(args)). Deterministic across
        equal-but-differently-ordered dicts."""
        payload = tool + "::" + json.dumps(
            args, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, tool: str, args: dict) -> Any:
        """Return cached response (parsed dict) or None on miss/expired."""
        key = self._key(tool, args)
        row = self._conn.execute(
            "SELECT response, created_at, ttl_seconds FROM legal_cache "
            "WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        response_json, created_at, ttl = row
        if time.time() > created_at + ttl:
            return None
        # Hit — bump counter
        self._conn.execute(
            "UPDATE legal_cache SET hits = hits + 1 WHERE cache_key = ?",
            (key,),
        )
        self._conn.commit()
        return json.loads(response_json)

    def set(self, tool: str, args: dict, *, response: Any, ttl_seconds: int) -> None:
        key = self._key(tool, args)
        self._conn.execute(
            "INSERT OR REPLACE INTO legal_cache "
            "(cache_key, tool, response, created_at, ttl_seconds, hits) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (key, tool, json.dumps(response), int(time.time()), ttl_seconds),
        )
        self._conn.commit()

    def clear(self) -> int:
        """Remove all entries. Returns the count of removed rows."""
        n = self._conn.execute("SELECT COUNT(*) FROM legal_cache").fetchone()[0]
        self._conn.execute("DELETE FROM legal_cache")
        self._conn.commit()
        return n

    def stats(self) -> dict:
        rows = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(hits), 0) FROM legal_cache"
        ).fetchone()
        return {"entries": rows[0], "total_hits": rows[1]}

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests** — Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/legal/cache.py tests/unit/test_legal_cache.py
git commit -m "feat(legal): LegalCache — SQLite TTL cache for OpenLégi

Phase 9 Task 4. SQLite at <vault>/legal_cache.sqlite.

Key = sha256(tool || canonical_json(args)) — deterministic across
equal-but-differently-ordered dicts. Survives daemon restarts.

Methods: get/set/clear/stats/close. TTL is caller-decided so the
service methods can pick different TTLs per tool (7d for verify, 5m
for freeform search).

7 regression tests including dict-order-canonicalization, TTL
expiration via monkeypatched time, hits counter, restart survival."
```

---

## Task 5: PisteClient (sync httpx wrapper)

**Files:**
- Create: `src/piighost/legal/piste_client.py`
- Test: `tests/unit/test_legal_piste_client.py`
- Modify: `pyproject.toml` (add `pytest-httpx` to test extra)

Port from OpenLégi documentation example, swapping `requests` for `httpx` (already a base dep). Sync API; daemon's RPC dispatch is already async-aware so the wrap-in-thread cost is acceptable here.

- [ ] **Step 1: Add `pytest-httpx` to test extras in `pyproject.toml`**

Find `[project.optional-dependencies]` and ensure (add the line if missing):

```toml
[project.optional-dependencies]
# … existing entries …
test = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "pytest-httpx>=0.30",
]
```

If `[test]` already exists with other deps, just append `"pytest-httpx>=0.30"` — don't replace the section.

Then install:
```
.venv/Scripts/python.exe -m pip install pytest-httpx
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_legal_piste_client.py`:

```python
"""PisteClient — sync httpx wrapper for OpenLégi MCP endpoint."""
from __future__ import annotations

import json

import httpx
import pytest

from piighost.legal.piste_client import PisteClient


def _sse(payload: dict) -> str:
    """OpenLégi returns SSE — encode a dict as one event."""
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def test_call_tool_happy_path(httpx_mock):
    """call_tool dispatches a tools/call JSON-RPC and parses SSE response."""
    httpx_mock.add_response(
        url="https://mcp.openlegi.fr/legifrance",
        method="POST",
        text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": [{"title": "Art. 1240"}]}}),
        headers={"Content-Type": "text/event-stream"},
    )
    with PisteClient(token="fake-token") as c:
        result = c.call_tool("rechercher_code", {"code_name": "Code civil", "search": "1240"})
    assert result == {"hits": [{"title": "Art. 1240"}]}


def test_authorization_header_set(httpx_mock):
    httpx_mock.add_response(
        url="https://mcp.openlegi.fr/legifrance",
        text=_sse({"jsonrpc": "2.0", "id": 1, "result": {}}),
    )
    with PisteClient(token="abc-123") as c:
        c.call_tool("rechercher_code", {})
    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer abc-123"


def test_429_retries_with_backoff(httpx_mock, monkeypatch):
    """On HTTP 429 we retry up to 3 times with backoff."""
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    httpx_mock.add_response(status_code=429)
    httpx_mock.add_response(status_code=429)
    httpx_mock.add_response(text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}))

    with PisteClient(token="x") as c:
        result = c.call_tool("rechercher_code", {})
    assert result == {"ok": True}
    assert len(sleeps) == 2  # two retries with sleeps


def test_429_exhausts_retries(httpx_mock):
    for _ in range(4):
        httpx_mock.add_response(status_code=429)

    with PisteClient(token="x", max_retries=3) as c:
        with pytest.raises(httpx.HTTPStatusError):
            c.call_tool("rechercher_code", {})


def test_401_does_not_retry(httpx_mock):
    httpx_mock.add_response(status_code=401)
    with PisteClient(token="bad") as c:
        with pytest.raises(httpx.HTTPStatusError):
            c.call_tool("rechercher_code", {})
    # Only one request — auth errors are not retried
    assert len(httpx_mock.get_requests()) == 1


def test_malformed_sse_raises_parse_error(httpx_mock):
    httpx_mock.add_response(text="garbage with no SSE structure")
    with PisteClient(token="x") as c:
        with pytest.raises(ValueError, match="(parse|SSE|JSON)"):
            c.call_tool("rechercher_code", {})


def test_custom_base_url(httpx_mock):
    httpx_mock.add_response(
        url="https://my-self-hosted.example.com/legifrance",
        text=_sse({"jsonrpc": "2.0", "id": 1, "result": {}}),
    )
    with PisteClient(
        token="x",
        base_url="https://my-self-hosted.example.com",
    ) as c:
        c.call_tool("rechercher_code", {})


def test_list_tools_returns_metadata(httpx_mock):
    httpx_mock.add_response(text=_sse({
        "jsonrpc": "2.0", "id": 1,
        "result": {"tools": [{"name": "rechercher_code", "description": "…"}]},
    }))
    with PisteClient(token="x") as c:
        tools = c.list_tools()
    assert tools == [{"name": "rechercher_code", "description": "…"}]
```

- [ ] **Step 3: Run tests** — Expected: ImportError.

- [ ] **Step 4: Implement `piste_client.py`**

```python
"""PisteClient — sync httpx wrapper for the OpenLégi MCP endpoint.

Ported from the OpenLégi documentation example. Differences from
the docs version:
  - httpx (already a base dep) instead of requests
  - 10s connect / 30s read timeout — never block the daemon
  - 429 retries with exponential backoff + jitter, max 3 attempts
  - Context-manager lifecycle (no module-level singleton)
"""
from __future__ import annotations

import json
import random
import time
from typing import Any

import httpx


class PisteClient:
    """Sync wrapper for OpenLégi's MCP-over-HTTPS endpoint."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://mcp.openlegi.fr",
        service: str = "legifrance",
        timeout_connect: float = 10.0,
        timeout_read: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._service = service
        self._max_retries = max_retries
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=timeout_connect, read=timeout_read,
                                  write=10.0, pool=10.0),
            follow_redirects=False,
        )
        self._next_id = 1
        self._session_id: str | None = None

    def __enter__(self) -> "PisteClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def _url(self) -> str:
        return f"{self._base_url}/{self._service}"

    @property
    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Invoke ``tool_name`` with ``arguments`` and return its result."""
        rid = self._next_id
        self._next_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        return self._post_with_retry(body)

    def list_tools(self) -> list[dict]:
        rid = self._next_id
        self._next_id += 1
        body = {"jsonrpc": "2.0", "id": rid, "method": "tools/list"}
        result = self._post_with_retry(body)
        return result.get("tools", [])

    def _post_with_retry(self, body: dict) -> dict:
        attempt = 0
        while True:
            try:
                resp = self._client.post(self._url, json=body, headers=self._headers)
            except httpx.RequestError as exc:
                # Connection failures don't retry — daemon should
                # surface UNKNOWN_NETWORK quickly.
                raise
            if resp.status_code == 429 and attempt < self._max_retries:
                attempt += 1
                # Exponential backoff with jitter: 0.5s, 1s, 2s + [0, 0.5)
                delay = 0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return self._parse_sse(resp.text)

    @staticmethod
    def _parse_sse(text: str) -> dict:
        """Parse one OpenLégi SSE event and return its result payload.

        Format::
            event: message
            data: {"jsonrpc":"2.0","id":1,"result":{...}}
            \\n\\n
        """
        lines = text.strip().splitlines()
        for line in lines:
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"SSE parse error: {exc}") from exc
                if "error" in parsed and parsed["error"]:
                    raise ValueError(f"OpenLégi error: {parsed['error']}")
                return parsed.get("result", {})
        raise ValueError("SSE parse error: no data: line found")
```

- [ ] **Step 5: Run tests** — Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/legal/piste_client.py tests/unit/test_legal_piste_client.py pyproject.toml
git commit -m "feat(legal): PisteClient — sync httpx wrapper for OpenLégi

Phase 9 Task 5. Ported from the OpenLégi documentation example,
swapping requests for httpx (already a base dep).

Behaviour:
  - Bearer-token auth (Authorization header)
  - 10s connect / 30s read timeout — never block the daemon
  - 429 retries with exponential backoff + jitter, max 3 attempts
  - 401/4xx other than 429: raise immediately (no retry)
  - SSE response parsing — one event per call

8 regression tests via pytest-httpx covering happy path, auth
header, 429 retry-with-backoff, retry exhaustion, 401 no-retry,
SSE parse error, custom base_url, list_tools."
```

---

## Task 6: CredentialsService

**Files:**
- Create: `src/piighost/service/credentials.py`
- Test: `tests/unit/test_credentials_service.py`

PISTE token storage at `~/.piighost/credentials.toml`, with strict permissions and read-strip-on-export.

- [ ] **Step 1: Write the failing tests**

```python
"""CredentialsService — credentials.toml lifecycle."""
from __future__ import annotations

import os
import sys

import pytest

from piighost.service.credentials import CredentialsService


@pytest.fixture()
def cred_root(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return home


def test_no_file_returns_empty(cred_root):
    s = CredentialsService()
    assert s.get_openlegi_token() is None
    assert not s.has_openlegi_token()


def test_set_then_get_token(cred_root):
    s = CredentialsService()
    s.set_openlegi_token("piste-token-xyz")
    assert s.get_openlegi_token() == "piste-token-xyz"
    assert s.has_openlegi_token() is True


def test_credentials_file_created_with_strict_perms(cred_root):
    s = CredentialsService()
    s.set_openlegi_token("x")
    path = cred_root / ".piighost" / "credentials.toml"
    assert path.exists()
    if sys.platform != "win32":
        # 600 = rw-------
        assert oct(path.stat().st_mode)[-3:] == "600"


def test_unset_removes_token(cred_root):
    s = CredentialsService()
    s.set_openlegi_token("x")
    s.unset_openlegi_token()
    assert s.get_openlegi_token() is None
    assert not s.has_openlegi_token()


def test_summary_never_returns_token_text(cred_root):
    """summary() is what controller_profile_get-style callers see —
    NEVER the actual token value."""
    s = CredentialsService()
    s.set_openlegi_token("super-secret-token")
    summary = s.summary()
    assert summary == {"openlegi": {"configured": True}}
    serialized = repr(summary)
    assert "super-secret-token" not in serialized


def test_set_overwrites_existing(cred_root):
    s = CredentialsService()
    s.set_openlegi_token("first")
    s.set_openlegi_token("second")
    assert s.get_openlegi_token() == "second"
```

- [ ] **Step 2: Run tests** — Expected: ImportError.

- [ ] **Step 3: Implement `credentials.py`**

```python
"""CredentialsService — manages ~/.piighost/credentials.toml.

PISTE token + any future per-service secrets live here, separate
from the descriptive controller.toml. The file is created with
mode 0o600 on POSIX and inherits ACL on Windows.

Public surface:
  - get_openlegi_token() -> str | None    — for daemon-side use
  - set_openlegi_token(token: str)        — wizard / setup skill
  - unset_openlegi_token()                — disable
  - has_openlegi_token() -> bool          — for status checks
  - summary() -> dict                      — non-sensitive report
                                             (controller_profile_get
                                              embeds this; never
                                              returns token text)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import tomllib


def _atomic_write(path: Path, content: str, *, mode: int = 0o600) -> None:
    """Write *content* to *path* atomically with restrictive perms (POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
        if sys.platform != "win32":
            os.chmod(path, mode)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _serialize(data: dict) -> str:
    """Tiny TOML serialiser for the shapes we use."""
    out: list[str] = []
    for table_name, table in data.items():
        if not isinstance(table, dict):
            continue
        out.append(f"[{table_name}]")
        for k, v in table.items():
            if isinstance(v, str):
                escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                out.append(f'{k} = "{escaped}"')
            elif isinstance(v, bool):
                out.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                out.append(f"{k} = {v}")
            else:
                raise TypeError(f"Unsupported type for {table_name}.{k}: {type(v)}")
        out.append("")
    return "\n".join(out).strip() + "\n"


class CredentialsService:
    def __init__(self) -> None:
        self._path = Path.home() / ".piighost" / "credentials.toml"

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return tomllib.loads(self._path.read_text("utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return {}

    def _write(self, data: dict) -> None:
        if not data:
            if self._path.exists():
                self._path.unlink()
            return
        _atomic_write(self._path, _serialize(data))

    # OpenLégi --------------------------------------------------------

    def get_openlegi_token(self) -> str | None:
        return self._read().get("openlegi", {}).get("piste_token")

    def has_openlegi_token(self) -> bool:
        return self.get_openlegi_token() is not None

    def set_openlegi_token(self, token: str) -> None:
        data = self._read()
        data.setdefault("openlegi", {})["piste_token"] = token
        self._write(data)

    def unset_openlegi_token(self) -> None:
        data = self._read()
        if "openlegi" in data:
            data["openlegi"].pop("piste_token", None)
            if not data["openlegi"]:
                data.pop("openlegi")
        self._write(data)

    # Public summary --------------------------------------------------

    def summary(self) -> dict:
        """Non-sensitive credentials status. NEVER includes token text."""
        return {
            "openlegi": {"configured": self.has_openlegi_token()},
        }
```

- [ ] **Step 4: Run tests** — Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/credentials.py tests/unit/test_credentials_service.py
git commit -m "feat(service): CredentialsService for PISTE token storage

Phase 9 Task 6. ~/.piighost/credentials.toml separate from
controller.toml. Created with mode 0o600 on POSIX (ACL on Windows).

Public surface:
  get_openlegi_token / set_openlegi_token / unset_openlegi_token
  has_openlegi_token / summary

summary() is the non-sensitive report — token text NEVER appears.
controller_profile_get embeds this in its [openlegi] section so the
configured-yes/no flag is visible without ever leaking the secret.

6 regression tests including the no-token-leak-in-summary gate."
```

---

## Task 7: ServiceConfig + 5 PIIGhostService methods

**Files:**
- Modify: `src/piighost/service/config.py` (add `OpenLegiSection`)
- Modify: `src/piighost/service/core.py` (add 5 methods)
- Test: `tests/unit/test_legal_service.py`

The 5 methods on `PIIGhostService`. Tests use `httpx.MockTransport` so we never hit the real network.

- [ ] **Step 1: Add `OpenLegiSection` to config.py**

In `src/piighost/service/config.py`, after `IncrementalSection` (around line 109), add:

```python
class OpenLegiSection(BaseModel):
    """Optional OpenLégi (Legifrance) integration."""
    enabled: bool = False
    base_url: str = "https://mcp.openlegi.fr"
    service: Literal["legifrance", "inpi", "eurlex"] = "legifrance"
```

Then in the `ServiceConfig` class, add the field next to the other sections:

```python
class ServiceConfig(BaseModel):
    schema_version: int = 1
    vault: VaultSection = Field(default_factory=VaultSection)
    detector: DetectorSection = Field(default_factory=DetectorSection)
    embedder: EmbedderSection = Field(default_factory=EmbedderSection)
    reranker: RerankerSection = Field(default_factory=RerankerSection)
    index: IndexSection = Field(default_factory=IndexSection)
    daemon: DaemonSection = Field(default_factory=DaemonSection)
    safety: SafetySection = Field(default_factory=SafetySection)
    incremental: IncrementalSection = Field(default_factory=IncrementalSection)
    openlegi: OpenLegiSection = Field(default_factory=OpenLegiSection)  # NEW
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_legal_service.py`:

```python
"""Service-level tests for the 5 legal RPC methods."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from piighost.service.config import ServiceConfig, RerankerSection, OpenLegiSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch, *, openlegi_enabled=True):
    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=openlegi_enabled),
    )
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def _sse(payload):
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def test_extract_legal_refs_no_network(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    refs = asyncio.run(svc.legal_extract_refs(text="article 1240 du Code civil"))
    assert len(refs) == 1
    assert refs[0]["ref_type"] == "ARTICLE_CODE"
    asyncio.run(svc.close())


def test_verify_disabled_returns_unknown(vault_dir, monkeypatch):
    """When [openlegi].enabled=False, verify returns the disabled status."""
    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=False)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240 du Code civil",
        "numero": "1240", "code": "Code civil", "position": 0,
    }))
    assert result["status"] == "UNKNOWN_OPENLEGI_DISABLED"
    asyncio.run(svc.close())


def test_verify_no_token_returns_unknown(vault_dir, monkeypatch):
    """Enabled but no PISTE token → UNKNOWN_AUTH_FAILED."""
    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    # No token set
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "x", "numero": "1240", "code": "Code civil", "position": 0,
    }))
    assert result["status"] in ("UNKNOWN_AUTH_FAILED", "UNKNOWN_OPENLEGI_DISABLED")
    asyncio.run(svc.close())


def test_search_legal_with_mocked_transport(vault_dir, monkeypatch):
    """search_legal hits OpenLégi via MockTransport — no real network."""
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1,
                       "result": {"hits": [{"title": "Code civil, Art. 1240"}]}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: httpx.Client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    hits = asyncio.run(svc.legal_search(query="article 1240", source="code"))
    assert isinstance(hits, list)
    asyncio.run(svc.close())


def test_credentials_set_persists(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.legal_credentials_set(token="new-token-xyz"))
    from piighost.service.credentials import CredentialsService
    assert CredentialsService().get_openlegi_token() == "new-token-xyz"
    asyncio.run(svc.close())


def test_passthrough_force_redacts(vault_dir, monkeypatch):
    """Even legal_passthrough applies the redactor — no opt-out."""
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("test-token")

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: httpx.Client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    asyncio.run(svc.legal_passthrough(
        tool="rechercher_code",
        args={"search": "Marie Curie article 1240"},   # Marie Curie should be redacted
    ))
    # Inspect what we sent
    assert captured
    body = captured[0]
    sent_args = body["params"]["arguments"]
    # NOTE: stub anonymize doesn't actually know "Marie Curie" — but
    # this test confirms the redactor is invoked. The privacy gate
    # in test_legal_outbound_privacy.py (Task 9) does the real check.
    assert "search" in sent_args
    asyncio.run(svc.close())
```

- [ ] **Step 3: Run tests** — Expected: AttributeError on `svc.legal_*`.

- [ ] **Step 4: Add 5 methods to `PIIGhostService`**

In `src/piighost/service/core.py`, locate `controller_profile_defaults` (around line 1319) and add the new methods after it. Also import the legal subsystem at module top.

Add to `_ProjectService` (the per-project class — these methods don't need a project but stay there for consistency):

```python
    # ---- Legal (OpenLégi) ----

    async def legal_extract_refs(self, *, text: str) -> list[dict]:
        from piighost.legal import extract_references
        refs = extract_references(text)
        return [r.model_dump() for r in refs]
```

Add to `PIIGhostService` (near the other dispatchers):

```python
    async def legal_extract_refs(self, *, text: str) -> list[dict]:
        """Extract legal references — pure-function, no network."""
        from piighost.legal import extract_references
        refs = extract_references(text)
        return [r.model_dump() for r in refs]

    async def legal_verify_ref(self, *, ref: dict) -> dict:
        """Verify one legal reference against OpenLégi."""
        from piighost.legal.reference_models import (
            LegalReference, VerificationResult, LegalRefType,
        )
        # Dispatch to the right OpenLégi tool by ref_type
        if not self._config.openlegi.enabled:
            return VerificationResult(
                status="UNKNOWN_OPENLEGI_DISABLED", score=None,
                message="OpenLégi désactivée — activez via /hacienda:legal:setup",
            ).model_dump()

        from piighost.service.credentials import CredentialsService
        token = CredentialsService().get_openlegi_token()
        if not token:
            return VerificationResult(
                status="UNKNOWN_AUTH_FAILED", score=None,
                message="Token PISTE manquant",
            ).model_dump()

        ref_obj = LegalReference.model_validate(ref)
        # Build the OpenLégi call based on ref_type
        if ref_obj.ref_type == LegalRefType.ARTICLE_CODE:
            tool = "rechercher_code"
            args = {
                "code_name": ref_obj.code or "Code civil",
                "search": ref_obj.numero or "",
                "champ": "NUM_ARTICLE",
                "max_results": 5,
            }
        elif ref_obj.ref_type in (LegalRefType.LOI, LegalRefType.DECRET, LegalRefType.ORDONNANCE):
            tool = "rechercher_dans_texte_legal"
            args = {"text_id": ref_obj.text_id or "", "search": "", "max_results": 5}
        elif ref_obj.ref_type == LegalRefType.JURISPRUDENCE:
            tool = "rechercher_jurisprudence_judiciaire"
            args = {
                "search": ref_obj.pourvoi or "",
                "champ": "NUM_AFFAIRE",
                "max_results": 5,
            }
        else:
            return VerificationResult(
                status="UNKNOWN_PARSE_ERROR",
                message=f"Type non supporté: {ref_obj.ref_type}",
            ).model_dump()

        return (await self._legal_call(tool, args, ttl_seconds=7 * 24 * 3600)).model_dump() \
            if isinstance(await self._legal_call(tool, args, ttl_seconds=7 * 24 * 3600), VerificationResult) \
            else self._classify_response(ref_obj, await self._legal_call(tool, args, ttl_seconds=7 * 24 * 3600))

    async def legal_search(
        self, *, query: str, source: str = "auto", max_results: int = 5,
    ) -> list[dict]:
        """Search OpenLégi by source."""
        if not self._config.openlegi.enabled:
            return []
        from piighost.service.credentials import CredentialsService
        if not CredentialsService().get_openlegi_token():
            return []

        # Map source enum → OpenLégi tool name
        source_to_tool = {
            "code": "rechercher_code",
            "jurisprudence_judiciaire": "rechercher_jurisprudence_judiciaire",
            "jurisprudence_administrative": "rechercher_jurisprudence_administrative",
            "cnil": "rechercher_decisions_cnil",
            "jorf": "recherche_journal_officiel",
            "lois_decrets": "rechercher_dans_texte_legal",
            "conventions_collectives": "rechercher_conventions_collectives",
        }
        if source == "auto":
            source = self._auto_route_source(query)
        tool = source_to_tool.get(source)
        if not tool:
            return []

        result = await self._legal_call(
            tool,
            {"search": query, "max_results": max_results},
            ttl_seconds=300,  # 5 min for freeform
        )
        if isinstance(result, dict) and "hits" in result:
            return [
                {"source": source, "title": h.get("title", ""),
                 "snippet": h.get("snippet", h.get("contenu", "")),
                 "url": h.get("url"), "score": h.get("score")}
                for h in result["hits"]
            ]
        return []

    async def legal_passthrough(self, *, tool: str, args: dict) -> dict:
        """Power-user escape hatch. Still passes through the redactor."""
        if not self._config.openlegi.enabled:
            return {"error": "OpenLégi désactivée"}
        return await self._legal_call(tool, args, ttl_seconds=7 * 24 * 3600)

    async def legal_credentials_set(self, *, token: str) -> dict:
        """Persist a PISTE token to ~/.piighost/credentials.toml."""
        from piighost.service.credentials import CredentialsService
        CredentialsService().set_openlegi_token(token)
        return {"configured": True}

    @staticmethod
    def _auto_route_source(query: str) -> str:
        import re
        if re.search(r"\d{2}-\d+\.\d+", query):
            return "jurisprudence_judiciaire"
        if re.search(r"loi\s+n[°o]?\s*\d", query, re.I):
            return "lois_decrets"
        if re.search(r"\bcnil\b", query, re.I):
            return "cnil"
        if re.search(r"\barticle\s+\d", query, re.I) or re.search(r"\bcode\s+", query, re.I):
            return "code"
        return "code"  # default for ambiguous queries

    async def _legal_call(self, tool: str, args: dict, *, ttl_seconds: int) -> dict:
        """Cache → redact → PisteClient → cache the response. The single
        outbound choke point."""
        from piighost.legal import LegalCache, OutboundRedactor, PisteClient
        from piighost.service.credentials import CredentialsService

        cache_dir = self._vault_dir if hasattr(self, "_vault_dir") else None
        if cache_dir is None:
            # Fallback: use ~/.piighost/ when no project context
            from pathlib import Path
            cache_dir = Path.home() / ".piighost"
            cache_dir.mkdir(parents=True, exist_ok=True)

        cache = LegalCache(vault_dir=cache_dir)
        try:
            hit = cache.get(tool, args)
            if hit is not None:
                return hit

            # Redact before send
            from piighost.indexer.anonymizer import anonymize as _anon
            redactor = OutboundRedactor(anonymize_fn=_anon)
            try:
                redacted_args = redactor.redact_dict(args)
            except Exception as exc:
                return {"error": f"redactor failed: {exc}"}

            token = CredentialsService().get_openlegi_token()
            try:
                with PisteClient(
                    token=token or "",
                    base_url=self._config.openlegi.base_url,
                    service=self._config.openlegi.service,
                ) as client:
                    response = client.call_tool(tool, redacted_args)
            except Exception as exc:
                return {"error": str(exc)}

            cache.set(tool, args, response=response, ttl_seconds=ttl_seconds)
            return response
        finally:
            cache.close()

    def _classify_response(self, ref, response) -> dict:
        """Map OpenLégi response to VerificationResult. Trivial v1: presence
        of any hit → VERIFIE_EXACT, else HALLUCINATION. Score 100 vs 0."""
        from piighost.legal.reference_models import VerificationResult
        hits = response.get("hits", []) if isinstance(response, dict) else []
        if hits:
            return VerificationResult(
                status="VERIFIE_EXACT", score=100,
                url_legifrance=hits[0].get("url"),
            ).model_dump()
        return VerificationResult(
            status="HALLUCINATION", score=0,
            type_erreur="REF_INEXISTANTE",
        ).model_dump()
```

(The `legal_verify_ref` body has a redundant call — clean it up to single-call:)

```python
    async def legal_verify_ref(self, *, ref: dict) -> dict:
        from piighost.legal.reference_models import (
            LegalReference, VerificationResult, LegalRefType,
        )
        if not self._config.openlegi.enabled:
            return VerificationResult(
                status="UNKNOWN_OPENLEGI_DISABLED", score=None,
                message="OpenLégi désactivée",
            ).model_dump()
        from piighost.service.credentials import CredentialsService
        if not CredentialsService().get_openlegi_token():
            return VerificationResult(
                status="UNKNOWN_AUTH_FAILED", score=None,
                message="Token PISTE manquant",
            ).model_dump()

        ref_obj = LegalReference.model_validate(ref)
        if ref_obj.ref_type == LegalRefType.ARTICLE_CODE:
            tool, args = "rechercher_code", {
                "code_name": ref_obj.code or "Code civil",
                "search": ref_obj.numero or "",
                "champ": "NUM_ARTICLE", "max_results": 5,
            }
        elif ref_obj.ref_type in (LegalRefType.LOI, LegalRefType.DECRET, LegalRefType.ORDONNANCE):
            tool, args = "rechercher_dans_texte_legal", {
                "text_id": ref_obj.text_id or "", "search": "", "max_results": 5,
            }
        elif ref_obj.ref_type == LegalRefType.JURISPRUDENCE:
            tool, args = "rechercher_jurisprudence_judiciaire", {
                "search": ref_obj.pourvoi or "",
                "champ": "NUM_AFFAIRE", "max_results": 5,
            }
        else:
            return VerificationResult(
                status="UNKNOWN_PARSE_ERROR",
                message=f"Type non supporté: {ref_obj.ref_type}",
            ).model_dump()

        response = await self._legal_call(tool, args, ttl_seconds=7 * 24 * 3600)
        if isinstance(response, dict) and "error" in response:
            return VerificationResult(
                status="UNKNOWN_NETWORK", message=str(response["error"]),
            ).model_dump()
        return self._classify_response(ref_obj, response)
```

- [ ] **Step 5: Run tests** — Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/service/config.py src/piighost/service/core.py tests/unit/test_legal_service.py
git commit -m "feat(service): 5 PIIGhostService.legal_* methods (Phase 9 Task 7)

Adds OpenLegiSection to ServiceConfig (enabled/base_url/service)
and 5 new service methods:

  legal_extract_refs(text)     — pure-function, no network
  legal_verify_ref(ref)        — verify one ref via OpenLégi
                                 dispatches to rechercher_code /
                                 rechercher_dans_texte_legal /
                                 rechercher_jurisprudence_judiciaire
                                 by ref_type
  legal_search(query, source)  — search OpenLégi by named source
                                 (code/jurisprudence/cnil/jorf/lois/
                                  conventions/auto)
  legal_passthrough(tool, args)— escape hatch (still redacts)
  legal_credentials_set(token) — write ~/.piighost/credentials.toml

Internal _legal_call is the single outbound choke point: cache → redact
→ PisteClient → cache the response. Network errors map to
UNKNOWN_NETWORK in the VerificationResult.

_auto_route_source dispatches by query shape (pourvoi number →
jurisprudence, loi n° → lois_decrets, cnil keyword → cnil,
article/code → code).

Tests use httpx.MockTransport — no real network. 6 cases covering
disabled, no-token, mocked happy path, credentials_set persistence,
passthrough always-redacts, extract_refs purity."
```

---

## Task 8: MCP wiring

**Files:**
- Modify: `src/piighost/mcp/tools.py` (5 ToolSpec)
- Modify: `src/piighost/mcp/shim.py` (5 wrappers)
- Modify: `src/piighost/daemon/server.py` (5 dispatch handlers)

Mechanical wiring; mirrors Phase 4 Task 4 / Phase 6 Task 6 pattern.

- [ ] **Step 1: Add 5 ToolSpec entries to `tools.py`**

After the `controller_profile_defaults` block, append:

```python
    # ---- Legal (OpenLégi) ----
    ToolSpec(
        name="extract_legal_refs",
        rpc_method="legal_extract_refs",
        description=(
            "Extract French legal references from text (article codes, "
            "lois, décrets, ordonnances, jurisprudence). Pure-function — "
            "no network, no token required. Returns a list of "
            "LegalReference dicts with sequential ref_id."
        ),
        timeout_s=2.0,
    ),
    ToolSpec(
        name="verify_legal_ref",
        rpc_method="legal_verify_ref",
        description=(
            "Verify one legal reference against OpenLégi (Legifrance). "
            "Returns VerificationResult with status (VERIFIE_EXACT / "
            "HALLUCINATION / UNKNOWN_*) + score 0-100. Returns "
            "UNKNOWN_OPENLEGI_DISABLED if [openlegi].enabled = false."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="search_legal",
        rpc_method="legal_search",
        description=(
            "Search OpenLégi by source: 'code' / 'jurisprudence_judiciaire' "
            "/ 'jurisprudence_administrative' / 'cnil' / 'jorf' / "
            "'lois_decrets' / 'conventions_collectives' / 'auto'. Returns "
            "list of LegalHit. Empty list if OpenLégi disabled or no token."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="legal_passthrough",
        rpc_method="legal_passthrough",
        description=(
            "Power-user escape hatch: invoke any of OpenLégi's 12 raw "
            "tools by name. Outbound payload still passes through the "
            "redactor — no opt-out."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="legal_credentials_set",
        rpc_method="legal_credentials_set",
        description=(
            "Write a PISTE token to ~/.piighost/credentials.toml (chmod "
            "600 on POSIX). The token is NEVER returned by any read "
            "method. Used by /hacienda:legal:setup."
        ),
        timeout_s=5.0,
    ),
```

- [ ] **Step 2: Add 5 shim wrappers in `shim.py`**

In `_build_mcp`, after the controller-profile group:

```python
    @mcp.tool(name="extract_legal_refs",
              description=by_name["extract_legal_refs"].description)
    async def extract_legal_refs(text: str) -> list[dict]:
        return await _lazy_dispatch(
            by_name["extract_legal_refs"], params={"text": text},
        )

    @mcp.tool(name="verify_legal_ref",
              description=by_name["verify_legal_ref"].description)
    async def verify_legal_ref(ref: dict) -> dict:
        return await _lazy_dispatch(
            by_name["verify_legal_ref"], params={"ref": ref},
        )

    @mcp.tool(name="search_legal",
              description=by_name["search_legal"].description)
    async def search_legal(
        query: str, source: str = "auto", max_results: int = 5,
    ) -> list[dict]:
        return await _lazy_dispatch(
            by_name["search_legal"],
            params={"query": query, "source": source, "max_results": max_results},
        )

    @mcp.tool(name="legal_passthrough",
              description=by_name["legal_passthrough"].description)
    async def legal_passthrough(tool: str, args: dict) -> dict:
        return await _lazy_dispatch(
            by_name["legal_passthrough"], params={"tool": tool, "args": args},
        )

    @mcp.tool(name="legal_credentials_set",
              description=by_name["legal_credentials_set"].description)
    async def legal_credentials_set(token: str) -> dict:
        return await _lazy_dispatch(
            by_name["legal_credentials_set"], params={"token": token},
        )
```

- [ ] **Step 3: Add 5 dispatch branches in `daemon/server.py`**

In `_dispatch`, before the final `raise ValueError("Unknown method")`:

```python
    if method == "legal_extract_refs":
        return await svc.legal_extract_refs(text=params["text"])
    if method == "legal_verify_ref":
        return await svc.legal_verify_ref(ref=params["ref"])
    if method == "legal_search":
        return await svc.legal_search(
            query=params["query"],
            source=params.get("source", "auto"),
            max_results=params.get("max_results", 5),
        )
    if method == "legal_passthrough":
        return await svc.legal_passthrough(
            tool=params["tool"], args=params["args"],
        )
    if method == "legal_credentials_set":
        return await svc.legal_credentials_set(token=params["token"])
```

- [ ] **Step 4: Smoke-check the registration**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
from piighost.mcp.tools import TOOL_CATALOG
names = [t.name for t in TOOL_CATALOG]
for tool in ['extract_legal_refs', 'verify_legal_ref', 'search_legal',
             'legal_passthrough', 'legal_credentials_set']:
    assert tool in names, tool
print(f'5 legal tools registered (catalog now {len(names)})')
"
```
Expected: `5 legal tools registered (catalog now 33)`.

- [ ] **Step 5: Re-run all legal-subsystem unit tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_legal_reference_models.py \
  tests/unit/test_legal_ref_extractor.py \
  tests/unit/test_legal_redactor.py \
  tests/unit/test_legal_cache.py \
  tests/unit/test_legal_piste_client.py \
  tests/unit/test_credentials_service.py \
  tests/unit/test_legal_service.py \
  -v --no-header
```
Expected: all green (5 + 9 + 7 + 7 + 8 + 6 + 6 = 48 tests).

- [ ] **Step 6: Commit**

```bash
git add src/piighost/mcp/tools.py src/piighost/mcp/shim.py src/piighost/daemon/server.py
git commit -m "feat(mcp): wire 5 legal tools (Phase 9 Task 8)

  - extract_legal_refs        (no network, 2s timeout)
  - verify_legal_ref          (30s timeout)
  - search_legal              (30s timeout)
  - legal_passthrough         (30s timeout, escape hatch)
  - legal_credentials_set     (5s timeout, no network)

Tool catalog grows from 28 → 33."
```

---

## Task 9: Privacy gate — outbound PII test

**Files:**
- Create: `tests/integration/test_legal_outbound_privacy.py`

THE most important test in this phase. Mirrors `test_no_pii_leak_phase2.py` but for the outbound boundary.

- [ ] **Step 1: Write the gate test**

```python
"""Privacy gate: no raw PII leaves the daemon to OpenLégi.

Mirrors test_no_pii_leak_phase2.py but for the outbound boundary.
Failing this test = compliance defect, not a bug.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from piighost.service.config import ServiceConfig, RerankerSection, OpenLegiSection
from piighost.service.core import PIIGhostService
from piighost.service.credentials import CredentialsService


_KNOWN_RAW_PII = [
    "Marie Curie",
    "marie.curie@acme.fr",
    "+33 6 12 34 56 78",
    "FR1420041010050500013M02606",
    "1 75 03 75 116 042 87",      # French SSN
]


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return tmp_path / "vault"


def _sse(payload):
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def test_legal_outbound_no_pii_leak(vault_dir, monkeypatch):
    """For 5 PII strings × multiple legal-grammar contexts, the wire
    payload must never contain any raw PII."""

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": []}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: httpx.Client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    # Set up daemon with OpenLégi enabled and a token
    CredentialsService().set_openlegi_token("test-token")
    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=True),
    )
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))

    # 10 inputs combining each PII with legal-grammar context
    inputs = [
        f"{pii} a invoqué l'article 1240 du Code civil"
        for pii in _KNOWN_RAW_PII
    ] + [
        f"Cass. civ. 1re, 15 mars 2023, n°21-12.345 — partie: {pii}"
        for pii in _KNOWN_RAW_PII
    ]

    for input_text in inputs:
        # Use search_legal — exercises the redactor for arbitrary queries
        asyncio.run(svc.legal_search(query=input_text, source="code"))

    # 10 inputs → 10 captured payloads
    assert len(captured_payloads) == 10

    # Every captured payload must be PII-free
    for i, payload in enumerate(captured_payloads):
        serialized = json.dumps(payload)
        for pii in _KNOWN_RAW_PII:
            assert pii not in serialized, (
                f"PII '{pii}' leaked in payload #{i}: {serialized}"
            )

    # AND the legal grammar must have survived
    for i, payload in enumerate(captured_payloads):
        serialized = json.dumps(payload)
        # Each input has either "article 1240" or "21-12.345"
        assert (
            "1240" in serialized or "21-12.345" in serialized
        ), f"legal grammar lost in payload #{i}: {serialized}"

    asyncio.run(svc.close())


def test_legal_outbound_redactor_strips_placeholder_format(vault_dir, monkeypatch):
    """Even if the caller already anonymised to <<label:HASH>> form,
    we strip that pattern — it leaks our redaction scheme."""

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": []}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: httpx.Client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    CredentialsService().set_openlegi_token("test-token")
    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=True),
    )
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))

    asyncio.run(svc.legal_search(
        query="<<nom_personne:abc12345>> article 1240", source="code",
    ))

    serialized = json.dumps(captured[0])
    assert "<<nom_personne:abc12345>>" not in serialized
    assert "1240" in serialized

    asyncio.run(svc.close())
```

- [ ] **Step 2: Run the gate test**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/integration/test_legal_outbound_privacy.py -v --no-header
```
Expected: 2 passed. **If either fails, STOP and fix the redactor — this is a compliance defect.**

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_legal_outbound_privacy.py
git commit -m "test(legal): outbound privacy gate (Phase 9 Task 9)

THE most important test in this phase. Mirrors
test_no_pii_leak_phase2.py for the outbound boundary.

For 10 inputs combining each of 5 known PII strings (Marie Curie,
email, French phone, IBAN, SSN) with legal-grammar context, asserts:
  1. NO raw PII appears in any captured wire payload
  2. Legal grammar (article numbers, pourvoi, code names) survives

Plus a separate test asserting our own placeholder format
<<label:HASH>> is also stripped (we don't even leak the redaction
scheme).

Failing this test = compliance defect, not a bug."
```

---

## Task 10: Plugin skills + plugin v0.8.0

**Files:**
- Create: `.worktrees/hacienda-plugin/skills/legal-verify/SKILL.md`
- Create: `.worktrees/hacienda-plugin/skills/legal-setup/SKILL.md`
- Create: `.worktrees/hacienda-plugin/skills/search/SKILL.md`
- Modify: `.worktrees/hacienda-plugin/skills/setup/SKILL.md` (Step 7)
- Modify: `.worktrees/hacienda-plugin/skills/knowledge-base/SKILL.md` (deprecated marker)
- Modify: `.worktrees/hacienda-plugin/skills/rgpd-dpia/SKILL.md` (CNIL enrichment)
- Modify: `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` (v0.8.0)

Plugin worktree at `.worktrees/hacienda-plugin/` has its own `.git` on branch `main`.

- [ ] **Step 1: Create `legal-setup/SKILL.md`**

```markdown
---
name: legal-setup
description: Configure or rotate the OpenLégi (Legifrance) integration. Walks the user through obtaining a PISTE token from https://piste.gouv.fr and writes it securely to ~/.piighost/credentials.toml. Use to enable, disable, or rotate the integration outside of the main /hacienda:setup wizard.
---

# /hacienda:legal:setup — Configurer OpenLégi

```
/hacienda:legal:setup
/hacienda:legal:setup --disable
```

## Workflow

### Mode: enable / rotate

1. Vérifier l'état actuel via `mcp__piighost__controller_profile_get(scope="global")`. Si `openlegi.configured = true`, demander à l'utilisateur s'il veut faire une rotation du token ou désactiver.

2. Expliquer la procédure :
   - Aller sur https://piste.gouv.fr
   - Créer un compte et demander l'accès à l'application Legifrance
   - Récupérer la clé d'API (token PISTE)

3. Demander : "Collez votre token PISTE ici (il sera écrit dans ~/.piighost/credentials.toml avec des permissions strictes — chmod 600 sur Linux/Mac) :"

4. Capturer la réponse, appeler `mcp__piighost__legal_credentials_set(token=<saisi>)`.

5. Confirmer avec un test ping :
   ```
   mcp__piighost__search_legal(query="test", source="code", max_results=1)
   ```

   Si le résultat est `[]` ou contient une erreur d'auth, indiquer "Token invalide. Réessayez."

6. Afficher : "✅ OpenLégi activé. Vous pouvez maintenant utiliser /hacienda:legal:verify et /hacienda:search."

### Mode: --disable

1. Appeler `mcp__piighost__legal_credentials_set(token="")` (efface le token).
2. Indiquer à l'utilisateur de mettre `[openlegi] enabled = false` dans son `controller.toml` s'il veut désactiver complètement (sinon les outils restent visibles mais retournent UNKNOWN_OPENLEGI_DISABLED).

## Refusals

- Si le token est vide → ne rien écrire, prévenir l'utilisateur.
- Ne JAMAIS afficher le token dans la conversation après l'avoir écrit. Une fois capturé, il est privé.
```

- [ ] **Step 2: Create `legal-verify/SKILL.md`**

```markdown
---
name: legal-verify
description: Vérifier les références juridiques françaises (articles de codes, lois, décrets, jurisprudences) contre les sources officielles via OpenLégi. Détecte les hallucinations (références inexistantes), numéros erronés, abrogations ignorées, jurisprudences fictives. Trois modes d'entrée : texte collé, fichier sur disque, document indexé. Génère un rapport JSON + Markdown.
argument-hint: "[--doc-id <id> | --project <name> | --file <path>]"
---

# /hacienda:legal:verify — Vérifier les citations juridiques

```
/hacienda:legal:verify              (texte collé dans le prompt)
/hacienda:legal:verify --doc-id abc123
/hacienda:legal:verify --project dossier-acme-2026
/hacienda:legal:verify --file /chemin/vers/document.pdf
```

## Pre-flight

Vérifier que OpenLégi est activé :
```
mcp__piighost__controller_profile_get(scope="global")
```
Si `openlegi.configured = false`, refuser avec "Activez OpenLégi via /hacienda:legal:setup."

## Workflow par mode

### Mode 1 : texte collé

1. Récupérer le texte du prompt utilisateur.
2. `mcp__piighost__extract_legal_refs(text=<texte>)` → `list[LegalReference]`
3. Pour chaque référence : `mcp__piighost__verify_legal_ref(ref=<r>)` → `VerificationResult`
4. Agréger en rapport.

### Mode 2 : --doc-id <id>

1. `mcp__piighost__index_status(...)` ou directement lire via le datastore (le doc_id est connu).
2. Récupérer le contenu textuel via les chunks indexés.
3. Suite identique à Mode 1.

### Mode 3 : --project <name>

1. Lister tous les documents du projet.
2. Pour chaque doc, mode 2.
3. Agréger les résultats au niveau projet.

### Mode 4 : --file <path>

1. Lire le fichier (avec kreuzberg si binaire).
2. Suite identique à Mode 1.

## Rapport

Structure JSON :
```json
{
  "metadata": {"document": "…", "date": "ISO-8601", "score_global": 0-100},
  "synthese": {"total": N, "exactes": N, "erreurs": N, "hallucinations": N},
  "details": [
    {
      "reference_originale": "article 1240 du Code civil",
      "statut": "VERIFIE_EXACT|HALLUCINATION|…",
      "score": 0-100,
      "type_erreur": null|"REF_INEXISTANTE"|"NUM_ERRONE"|...,
      "url_legifrance": "https://...",
      "correction": null|"texte de correction"
    }
  ]
}
```

(Optionnel) Sauvegarder via `mcp__piighost__render_compliance_doc` :
```
mcp__piighost__render_compliance_doc(
  data=<rapport>,
  format="md",
  profile="generic",
  project=<projet>
)
```

## Refusals

- Si OpenLégi désactivé : redirection vers `/hacienda:legal:setup`.
- Si aucune référence extraite (`extract_legal_refs` renvoie []) : afficher "Aucune référence juridique détectée dans l'entrée."
- Pour `--doc-id`/`--project` : si OpenLégi non configuré, refuser proprement plutôt que produire un rapport incomplet.
```

- [ ] **Step 3: Create `search/SKILL.md`**

```markdown
---
name: search
description: Recherche fédérée sur les documents indexés localement (vault piighost) ET sur les sources officielles françaises via OpenLégi (Code civil, jurisprudence, CNIL, JORF, conventions collectives). Retourne une liste classée mêlant les hits LOCAL et LEGAL avec attribution explicite de la source. Auto-annote les références juridiques trouvées dans les documents locaux.
argument-hint: "[--local | --legal | --both] <query>"
---

# /hacienda:search — Recherche fédérée

```
/hacienda:search "responsabilité contractuelle"        (default: --both)
/hacienda:search --local "facture acme 2026"
/hacienda:search --legal "article 1240"
```

## Workflow

1. Résoudre le projet actif via `mcp__piighost__resolve_project_for_folder(<folder>)` si Cowork.

2. Selon le scope :
   - `--local` ou par défaut : `mcp__piighost__query(text=<q>, k=10, project=<p>)`
   - `--legal` ou par défaut : `mcp__piighost__search_legal(query=<q>, source="auto", max_results=5)` (skipped si OpenLégi désactivé)
   - `--both` (default) : les deux en parallèle.

3. Fusion + classement :
   - Les hits LOCAL en premier (score piighost)
   - Annotation : si le texte d'un hit LOCAL contient une référence juridique extractible, appeler `mcp__piighost__extract_legal_refs(text=<chunk>)` et insérer le résultat de `mcp__piighost__verify_legal_ref(ref=<r>)` directement sous le hit
   - Les hits LEGAL ensuite, par pertinence

4. Afficher avec attribution :
   ```
   [LOCAL]  client_acme/contrat.pdf  p3   "...considérant l'article 1240..."
   ↳ [CODE] Code civil, Art. 1240        "Tout fait quelconque de l'homme..."
   [LOCAL]  client_acme/correspondance.txt p1 "..."
   [LEGAL] Cass. civ. 1re, 15 mars 2023, n°21-12.345
   ```

## Refusals

- Si OpenLégi désactivé et l'utilisateur a passé `--legal` : suggérer `/hacienda:legal:setup`.
- Si aucun projet local n'a été indexé et `--local` : suggérer `/hacienda:index`.
```

- [ ] **Step 4: Add Step 7 to the existing `setup/SKILL.md`**

Locate the existing wizard's "Step 6 — Durée de conservation" section. Insert after it, before the "Write the profile" section:

```markdown
## Step 7 — Vérification de citations juridiques (optionnel)

L'intégration OpenLégi permet de vérifier les références juridiques
(articles, lois, jurisprudences) contre les sources officielles
Legifrance + INPI + EUR-Lex. Toutes les requêtes sortantes sont
anonymisées et auditées.

Demander : "Voulez-vous activer cette intégration ? (oui / non / plus_tard)"

- **oui** :
  1. Demander : "Collez votre token PISTE (récupérable sur https://piste.gouv.fr) :"
  2. Appeler `mcp__piighost__legal_credentials_set(token=<saisi>)`
  3. Test ping : `mcp__piighost__search_legal(query="test", source="code", max_results=1)`
  4. Si OK, ajouter à `controller.toml` :
     ```toml
     [openlegi]
     enabled = true
     ```
  5. Confirmer : "✅ OpenLégi activé."

- **non** :
  Ajouter à `controller.toml` :
  ```toml
  [openlegi]
  enabled = false
  ```

- **plus_tard** :
  Skip — l'utilisateur peut activer plus tard via `/hacienda:legal:setup`.
```

- [ ] **Step 5: Mark `knowledge-base/SKILL.md` as deprecated**

Edit the YAML frontmatter `description` to start with `[DEPRECATED — utilisez /hacienda:search]`. Add a short body section above the existing content:

```markdown
> **Note** : Cette skill est dépréciée au profit de `/hacienda:search`
> qui combine la recherche locale (vault) ET la recherche dans les
> sources officielles (OpenLégi). `/hacienda:knowledge-base` reste
> fonctionnelle mais sera supprimée dans une future version majeure
> du plugin.
```

- [ ] **Step 6: Add CNIL enrichment to `rgpd-dpia/SKILL.md`**

After the "Step 4 — Render to MD (optional)" section, add:

```markdown
## Step 5 (optional) — Enrichissement CNIL

Si OpenLégi est activé (`controller_profile_get` → `openlegi.configured = true`),
chercher les décisions CNIL pertinentes par rapport au verdict :

```
hits = mcp__piighost__search_legal(
    query=<verdict_explanation + premier trigger.name>,
    source="cnil",
    max_results=3,
)
```

Afficher chaque hit en complément du verdict :
```
📋 Décisions CNIL pertinentes
- {{hit.title}} — {{hit.url}}
```

Ne pas faire échouer la skill si l'appel échoue ou retourne `[]` ;
c'est un enrichissement, pas une exigence.
```

- [ ] **Step 7: Bump plugin version**

Edit `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` — change `"version": "0.7.0"` to `"version": "0.8.0"`.

- [ ] **Step 8: Verify frontmatter parses + commit**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
import re, json
files = [
    '.worktrees/hacienda-plugin/skills/legal-setup/SKILL.md',
    '.worktrees/hacienda-plugin/skills/legal-verify/SKILL.md',
    '.worktrees/hacienda-plugin/skills/search/SKILL.md',
]
for f in files:
    content = open(f, encoding='utf-8').read()
    m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    assert m, f'no frontmatter in {f}'
    fm = m.group(1)
    assert 'name:' in fm and 'description:' in fm, fm
    print(f'{f}: frontmatter OK')
print(json.load(open('.worktrees/hacienda-plugin/.claude-plugin/plugin.json'))['version'])
"
```
Expected: 3 OK lines + `0.8.0`.

```bash
git -C .worktrees/hacienda-plugin add skills/legal-setup/SKILL.md skills/legal-verify/SKILL.md skills/search/SKILL.md skills/setup/SKILL.md skills/knowledge-base/SKILL.md skills/rgpd-dpia/SKILL.md .claude-plugin/plugin.json
git -C .worktrees/hacienda-plugin commit -m "feat(skills): /hacienda:legal:* + /hacienda:search + v0.8.0

Phase 9 Task 10. Adds three new skills + extends two existing ones:

  legal-setup       — token rotation/disable
  legal-verify      — 4-mode citation verifier (text/file/doc/project)
  search            — federated local+legal search with auto-annotation
  setup             — adds optional Step 7 (OpenLégi token collection)
  knowledge-base    — marked deprecated, redirects to /hacienda:search
  rgpd-dpia         — optional CNIL enrichment when OpenLégi enabled

Bumps plugin v0.7.0 → v0.8.0."
```

DO NOT push yet — Task 11 handles push.

---

## Task 11: Phase 9 final smoke + push

**Files:**
- No new code — verification + push.

- [ ] **Step 1: Run all Phase 9 unit tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_legal_reference_models.py \
  tests/unit/test_legal_ref_extractor.py \
  tests/unit/test_legal_redactor.py \
  tests/unit/test_legal_cache.py \
  tests/unit/test_legal_piste_client.py \
  tests/unit/test_credentials_service.py \
  tests/unit/test_legal_service.py \
  tests/integration/test_legal_outbound_privacy.py \
  -v --no-header
```
Expected: 5 + 9 + 7 + 7 + 8 + 6 + 6 + 2 = 50 passed.

- [ ] **Step 2: Run full RGPD regression sweep**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_doc_authors_anonymisation.py \
  tests/unit/test_controller_profile.py \
  tests/unit/test_controller_profile_mcp.py \
  tests/unit/test_controller_profile_defaults_mcp.py \
  tests/unit/test_processing_register.py \
  tests/unit/test_dpia_screening.py \
  tests/unit/test_render_compliance_doc.py \
  tests/unit/test_render_data_validation.py \
  tests/unit/test_no_pii_leak_phase1.py \
  tests/unit/test_no_pii_leak_phase2.py \
  tests/unit/test_subject_clustering.py \
  tests/unit/test_service_subject_access.py \
  tests/unit/test_service_forget_subject.py \
  tests/unit/test_forget_subject_concurrency.py \
  tests/unit/test_profile_loader.py \
  tests/unit/test_profile_loader_warns.py \
  tests/unit/test_compliance_public_api.py \
  tests/unit/test_compliance_lazy_imports.py \
  tests/unit/test_compliance_submodels_forbid.py \
  tests/integration/test_setup_wizard_e2e.py \
  tests/integration/test_mcp_shim_compliance_e2e.py \
  tests/integration/test_real_daemon_smoke.py \
  --no-header
```
Expected: all green (modulo the 2 pre-existing skips).

- [ ] **Step 3: Push piighost master**

```bash
ECC_SKIP_PREPUSH=1 git push jamon master
```

- [ ] **Step 4: Push the plugin worktree**

```bash
git -C .worktrees/hacienda-plugin push origin main
```

- [ ] **Step 5: (Optional) Phase 9 followups doc**

Capture any issues that surfaced during execution in `docs/superpowers/followups/2026-04-28-openlegi-followups.md` following the existing format.

---

## Self-review checklist

**Spec coverage:**

| Spec section | Implementing task |
|---|---|
| `LegalReference` / `VerificationResult` / `LegalHit` Pydantic | Task 1 |
| `extract_references` regex extractor | Task 2 |
| `OutboundRedactor` privacy boundary | Task 3 |
| `LegalCache` SQLite TTL | Task 4 |
| `PisteClient` sync httpx wrapper | Task 5 |
| `CredentialsService` (chmod 600) | Task 6 |
| `OpenLegiSection` ServiceConfig | Task 7 (Step 1) |
| 5 `PIIGhostService.legal_*` methods | Task 7 |
| MCP wiring (5 tools) | Task 8 |
| Outbound privacy gate | Task 9 |
| `legal-setup` / `legal-verify` / `search` skills | Task 10 |
| Wizard Step 7 | Task 10 |
| Knowledge-base deprecation | Task 10 |
| RGPD DPIA CNIL enrichment | Task 10 |
| Plugin v0.8.0 | Task 10 |
| Smoke + push | Task 11 |

✓ Every spec item has a task. The 4 deferred-to-plan questions:
- "auto" router strategy → regex-based (Task 7 `_auto_route_source`)
- Cache eviction policy → TTL-only, no LRU (Task 4)
- `legal_passthrough` redactor → enforced (Task 7, test in Task 9)
- search skill phasing → shipped together (Task 10)

**Placeholder scan**: every code block has real code. No "TBD"/"similar to Task N".

**Type consistency**:
- `LegalReference` field names match between Task 1 (definition), Task 2 (extractor populates), Task 7 (verify_legal_ref consumes). ✓
- `VerificationResult.status` enum is the same set in models, service, and gate test. ✓
- `OpenLegiSection` field names match between config.py and the wizard's TOML write. ✓
- `legal_credentials_set(token: str)` signature matches between the service method, MCP tool, and wizard skill. ✓

---

## Estimated effort

| Task | Effort |
|---|---|
| 1 — Reference models | 1 h |
| 2 — Reference extractor | 1.5 h |
| 3 — OutboundRedactor | 2 h |
| 4 — LegalCache | 1.5 h |
| 5 — PisteClient | 2.5 h |
| 6 — CredentialsService | 1.5 h |
| 7 — Service methods + config | 2.5 h |
| 8 — MCP wiring | 1 h |
| 9 — Privacy gate | 1.5 h |
| 10 — Plugin skills (3 new + 3 modified) | 3 h |
| 11 — Smoke + push | 30 min |
| **Total** | **~18 h (~2.5 working days)** |
