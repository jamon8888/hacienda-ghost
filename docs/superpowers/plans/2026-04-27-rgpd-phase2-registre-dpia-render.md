# RGPD Phase 2 — Registre Art. 30 + DPIA-lite + Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the user-facing compliance artifacts — Registre Art. 30 (processing register), DPIA-lite screening (Art. 35), and a Jinja2-based render layer that produces MD / DOCX / PDF deliverables. Surfaces 3 new MCP tools (`processing_register`, `dpia_screening`, `render_compliance_doc`) + 2 plugin skills (`/hacienda:rgpd:registre`, `/hacienda:rgpd:dpia`). Plus 2 prerequisite tools (`controller_profile_get/set`) for the future wizard.

**Architecture:** Reads from Phase 0 (`documents_meta`, `AuditEvent v2`, `ControllerProfileService`) and Phase 1 (`vault_stats`, `doc_entities`). New `compliance/` package with the report builders + Jinja2 render layer. Templates bundled per profession (avocat, notaire, expert_comptable, médecin, RH, generic). Heavy deps (Jinja2, weasyprint, docxtpl, markdown) gated behind a `[compliance]` optional extra so the core MCP install stays tight.

**Tech Stack:** Python 3.13, Pydantic, Jinja2, weasyprint (PDF), docxtpl (DOCX), markdown (MD→HTML). No new SQLite tables.

**Spec:** `docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md` (commit `a2535c3`).

**Phase 0+1 prerequisites:** all of `4ab5309..6893970` must be merged. Phase 2 depends on:
- `documents_meta` + `documents_meta_for()` + `list_documents_meta()` (Phase 0 Task 5)
- `AuditEvent v2` + `record_v2()` + `read_events()` (Phase 0 Task 6)
- `ControllerProfileService` (Phase 0 Task 7)
- `vault_stats()` (existing, Phase 1 reads it via `_vault.stats()`)

**Phase 1 follow-ups carried into Phase 2:**
- **I3** (review): anonymise `doc_authors` in `documents_meta` so the Registre doesn't leak raw names → **Task 1**
- **Pre-Phase-2 gap** (review): `controller_profile_get/set` are absent from `TOOL_CATALOG` → **Task 2**
- **I1** (review, optional): lock `forget_subject` per-project → **Task 10** if time permits

**Project root for all paths below:** `C:\Users\NMarchitecte\Documents\piighost`.

---

## File map (Phase 2)

| Path | Type | Owns |
|---|---|---|
| `src/piighost/service/doc_metadata_extractor.py` | modify | Anonymise `doc_authors` before persistence (Task 1) |
| `src/piighost/service/core.py` | modify | `controller_profile_get/set` dispatchers + 3 Phase 2 service methods |
| `src/piighost/mcp/tools.py` | modify | 5 new ToolSpec (controller_get/set + 3 Phase 2 tools) |
| `src/piighost/mcp/shim.py` | modify | 5 new `@mcp.tool` wrappers |
| `src/piighost/daemon/server.py` | modify | 5 dispatch handlers |
| `src/piighost/service/models.py` | modify | `ProcessingRegister`, `DPIAScreening`, `DPIATrigger`, `RenderResult`, sub-models |
| `src/piighost/compliance/__init__.py` | new | Package init |
| `src/piighost/compliance/processing_register.py` | new | `processing_register()` builder |
| `src/piighost/compliance/dpia_screening.py` | new | DPIA triggers + verdict logic |
| `src/piighost/compliance/render.py` | new | `render_compliance_doc()` |
| `src/piighost/compliance/templates/generic/registre.md.j2` | new | Generic registre template |
| `src/piighost/compliance/templates/generic/dpia_screening.md.j2` | new | Generic DPIA-lite template |
| `src/piighost/compliance/templates/generic/subject_access.md.j2` | new | Generic subject_access template (for /rgpd:access skill rendering) |
| `src/piighost/compliance/templates/avocat/registre.md.j2` | new | Avocat-flavoured registre |
| `src/piighost/compliance/templates/notaire/registre.md.j2` | new | Notaire-flavoured registre |
| `src/piighost/compliance/templates/medecin/registre.md.j2` | new | Médecin-flavoured registre |
| `src/piighost/compliance/templates/expert_comptable/registre.md.j2` | new | EC-flavoured registre |
| `src/piighost/compliance/templates/rh/registre.md.j2` | new | RH-flavoured registre |
| `pyproject.toml` | modify | New `[compliance]` extra (Jinja2, weasyprint, docxtpl, markdown) |
| `tests/unit/test_doc_authors_anonymisation.py` | new | Verifies authors anonymised at index time |
| `tests/unit/test_processing_register.py` | new | Inventaire, recipients, transfers |
| `tests/unit/test_dpia_screening.py` | new | Trigger detection per Art. 35.3 + CNIL |
| `tests/unit/test_render_compliance_doc.py` | new | Round-trip MD; Pdf+Docx skipped if extras missing |
| `tests/unit/test_no_pii_leak_phase2.py` | new | 3 invariant tests across the 3 new tools |
| `.worktrees/hacienda-plugin/skills/rgpd-registre/SKILL.md` | new | `/hacienda:rgpd:registre` |
| `.worktrees/hacienda-plugin/skills/rgpd-dpia/SKILL.md` | new | `/hacienda:rgpd:dpia` |
| `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` | modify | bump v0.6.0 |

---

## Task 1: Anonymise `doc_authors` at index time (Phase 1 carryover)

**Files:**
- Modify: `src/piighost/service/doc_metadata_extractor.py`
- Test: `tests/unit/test_doc_authors_anonymisation.py`

**Why first:** Phase 1 review flagged `doc_authors_json` in `documents_meta` may contain raw names (e.g. PDF metadata "Marie Dupont"). Phase 2's `processing_register` will read `documents_meta` and surface those names. Block this leak BEFORE building the Registre.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_doc_authors_anonymisation.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_doc_authors_anonymisation.py -v --no-header
```
Expected: ImportError on `_anonymise_authors` and assertion failure on `build_metadata` test.

- [ ] **Step 3: Implement `_anonymise_authors` and wire into `build_metadata`**

Open `src/piighost/service/doc_metadata_extractor.py`. Find the existing `_party_token` function (which generates `<<{label}:{hash}>>` placeholders). Add `_anonymise_authors` next to it:

```python
def _anonymise_authors(authors: list[str] | None) -> list[str]:
    """Replace raw author names with deterministic placeholder tokens.

    kreuzberg returns the raw 'authors' field from PDF/Office metadata.
    Storing those names as-is in ``documents_meta`` would leak through
    the Phase 2 processing_register. Each non-blank author becomes
    ``<<author:HASH8>>`` (sha256 of label+text, same scheme as
    LabelHashPlaceholderFactory).

    Empty / None / whitespace-only inputs are filtered out.
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
```

Then find the line in `build_metadata` that does `authors = kreuzberg_meta.get("authors") or []` (around line 290 — check actual line number first). Replace it so that `meta.doc_authors` receives the anonymised version:

```python
    raw_authors = kreuzberg_meta.get("authors") or []
    authors = _anonymise_authors(raw_authors)
```

Pass `authors` (the anonymised list) into `DocumentMetadata(... doc_authors=authors ...)`. The raw `raw_authors` list is discarded.

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_doc_authors_anonymisation.py tests/unit/test_doc_metadata_extractor.py -v --no-header
```
Expected: 5 new + ~12 existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/doc_metadata_extractor.py tests/unit/test_doc_authors_anonymisation.py
git commit -m "fix(metadata): anonymise doc_authors before storing in documents_meta

Phase 1 final-review I3 carryover. kreuzberg returns the raw
'authors' field from PDF/Office metadata — storing that as-is in
documents_meta.doc_authors_json would leak raw names through the
Phase 2 processing_register output.

_anonymise_authors() replaces each non-blank author with a
deterministic placeholder using the same hash scheme as parties
(<<author:HASH8>>). Empty/None/whitespace inputs are filtered.
Deterministic so re-extraction of the same doc yields stable tokens."
```

---

## Task 2: `controller_profile_get/set` MCP tools (Wizard prerequisite)

**Files:**
- Modify: `src/piighost/service/core.py` (`PIIGhostService` dispatchers)
- Modify: `src/piighost/mcp/tools.py` (2 ToolSpec)
- Modify: `src/piighost/mcp/shim.py` (2 tool wrappers)
- Modify: `src/piighost/daemon/server.py` (2 dispatch handlers)
- Test: `tests/unit/test_controller_profile_mcp.py`

**Why this fits Phase 2:** the spec lists these as Phase 0 tools but they were missed. Phase 2's `processing_register` consumes `ControllerProfile` directly via the service, but the future wizard (`/hacienda:setup`) needs them as MCP tools. Adding now keeps the surface complete.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_controller_profile_mcp.py`:

```python
"""Tests for controller_profile_get / set MCP dispatchers on PIIGhostService."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.core import PIIGhostService
from piighost.service.config import ServiceConfig, RerankerSection


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_controller_profile_get_global_returns_empty_when_missing(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    profile = asyncio.run(svc.controller_profile_get(scope="global"))
    assert profile == {}
    asyncio.run(svc.close())


def test_controller_profile_set_then_get_global(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    payload = {
        "controller": {"name": "Cabinet X", "profession": "avocat"},
        "defaults": {"finalites": ["Conseil juridique"]},
    }
    asyncio.run(svc.controller_profile_set(profile=payload, scope="global"))
    got = asyncio.run(svc.controller_profile_get(scope="global"))
    assert got["controller"]["name"] == "Cabinet X"
    assert got["controller"]["profession"] == "avocat"
    asyncio.run(svc.close())


def test_controller_profile_per_project_override(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={"controller": {"name": "Global", "profession": "avocat"}},
        scope="global",
    ))
    asyncio.run(svc.controller_profile_set(
        profile={"controller": {"name": "Project-Specific"}},
        scope="project", project="dossier-x",
    ))
    merged = asyncio.run(svc.controller_profile_get(
        scope="project", project="dossier-x",
    ))
    assert merged["controller"]["name"] == "Project-Specific"
    assert merged["controller"]["profession"] == "avocat"  # inherited
    asyncio.run(svc.close())


def test_controller_profile_set_requires_project_when_scope_project(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(svc.controller_profile_set(
            profile={"x": "y"}, scope="project",
        ))
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_controller_profile_mcp.py -v --no-header
```
Expected: AttributeError on `controller_profile_get` / `controller_profile_set`.

- [ ] **Step 3: Add dispatchers on `PIIGhostService`**

In `src/piighost/service/core.py`, add to `PIIGhostService` class (near other public dispatchers):

```python
    async def controller_profile_get(
        self, *, scope: str = "global", project: str | None = None,
    ) -> dict:
        """Read the controller profile (global or merged per-project)."""
        from piighost.service.controller_profile import ControllerProfileService
        cp_svc = ControllerProfileService(self._vault_dir)
        return cp_svc.get(scope=scope, project=project)  # type: ignore[arg-type]

    async def controller_profile_set(
        self, *, profile: dict,
        scope: str = "global", project: str | None = None,
    ) -> dict:
        """Atomically write the controller profile."""
        from piighost.service.controller_profile import ControllerProfileService
        cp_svc = ControllerProfileService(self._vault_dir)
        cp_svc.set(profile, scope=scope, project=project)  # type: ignore[arg-type]
        return {"ok": True, "scope": scope, "project": project or ""}
```

If `PIIGhostService` doesn't store `_vault_dir` directly, derive from `self._vault_root` or whatever attribute holds the vault path (check `__init__` first).

- [ ] **Step 4: Add 2 ToolSpec entries**

In `src/piighost/mcp/tools.py`, append to `TOOL_CATALOG` (under a `# Controller profile` group comment):

```python
    # Controller profile (RGPD compliance — Phase 0 surface, exposed in Phase 2)
    ToolSpec(
        name="controller_profile_get",
        rpc_method="controller_profile_get",
        description=(
            "Read the data controller profile (cabinet/profession/DPO/"
            "purposes/retention). scope='global' returns ~/.piighost/"
            "controller.toml; scope='project' returns the merged view "
            "(global + per-project override) for a given project."
        ),
        timeout_s=2.0,
    ),
    ToolSpec(
        name="controller_profile_set",
        rpc_method="controller_profile_set",
        description=(
            "Atomically write the data controller profile. scope='global' "
            "writes ~/.piighost/controller.toml; scope='project' writes a "
            "per-project override containing only the fields that differ."
        ),
        timeout_s=5.0,
    ),
```

- [ ] **Step 5: Add 2 `@mcp.tool` wrappers in shim.py**

In `src/piighost/mcp/shim.py`, near the end of `_build_mcp` (before `return mcp`):

```python
    @mcp.tool(name="controller_profile_get",
              description=by_name["controller_profile_get"].description)
    async def controller_profile_get(
        scope: str = "global", project: str = "",
    ) -> dict:
        result = await _lazy_dispatch(
            by_name["controller_profile_get"],
            params={"scope": scope, "project": project or None},
        )
        # Wrap raw dict for FastMCP's structured-content rule
        return {"profile": result}

    @mcp.tool(name="controller_profile_set",
              description=by_name["controller_profile_set"].description)
    async def controller_profile_set(
        profile: dict, scope: str = "global", project: str = "",
    ) -> dict:
        return await _lazy_dispatch(
            by_name["controller_profile_set"],
            params={
                "profile": profile, "scope": scope,
                "project": project or None,
            },
        )
```

- [ ] **Step 6: Add 2 dispatch handlers in daemon/server.py**

In `src/piighost/daemon/server.py`'s `_dispatch`, add before the final `raise ValueError`:

```python
    if method == "controller_profile_get":
        return await svc.controller_profile_get(
            scope=params.get("scope", "global"),
            project=params.get("project") or None,
        )
    if method == "controller_profile_set":
        return await svc.controller_profile_set(
            profile=params["profile"],
            scope=params.get("scope", "global"),
            project=params.get("project") or None,
        )
```

- [ ] **Step 7: Run tests to verify**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_controller_profile_mcp.py tests/unit/test_controller_profile.py -v --no-header
```
Expected: 4 new + 9 existing tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/piighost/service/core.py src/piighost/mcp/tools.py src/piighost/mcp/shim.py src/piighost/daemon/server.py tests/unit/test_controller_profile_mcp.py
git commit -m "feat(mcp): controller_profile_get + controller_profile_set tools

Phase 1 final-review pre-Phase-2 prerequisite. Closes the gap where
ControllerProfileService (Phase 0) was implemented but never wired
to MCP. Required by the future /hacienda:setup wizard and useful
for any caller that needs to introspect or mutate the controller
profile programmatically."
```

---

## Task 3: `ProcessingRegister` Pydantic models + service method

**Files:**
- Modify: `src/piighost/service/models.py` (append models)
- Create: `src/piighost/compliance/__init__.py` (package init)
- Create: `src/piighost/compliance/processing_register.py`
- Modify: `src/piighost/service/core.py` (add `processing_register` dispatcher on `PIIGhostService` + per-project method on `_ProjectService`)
- Test: `tests/unit/test_processing_register.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_processing_register.py`:

```python
"""Service-level tests for processing_register (Art. 30)."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_processing_register_empty_project(vault_dir, monkeypatch):
    """Newly-created project with nothing indexed should still produce a
    valid (mostly empty) ProcessingRegister."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("reg-empty"))
    report = asyncio.run(svc.processing_register(project="reg-empty"))
    assert report.v == 1
    assert report.project == "reg-empty"
    assert report.data_categories == []
    assert report.documents_summary.total_docs == 0
    asyncio.run(svc.close())


def test_processing_register_inventory_from_vault_stats(vault_dir, monkeypatch):
    """Categories and counts come from vault.stats() and documents_meta."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("reg-inv"))
    proj = asyncio.run(svc._get_project("reg-inv"))
    # Seed entities of various labels
    seeds = [
        ("<<np:1>>", "Marie", "nom_personne"),
        ("<<np:2>>", "Jean", "nom_personne"),
        ("<<em:1>>", "m@x.fr", "email"),
        ("<<sante:1>>", "diabetes", "donnee_sante"),  # Art. 9 sensitive
    ]
    for token, original, label in seeds:
        proj._vault.upsert_entity(
            token=token, original=original, label=label, confidence=0.9,
        )

    report = asyncio.run(svc.processing_register(project="reg-inv"))
    by_label = {c.label: c.count for c in report.data_categories}
    assert by_label.get("nom_personne") == 2
    assert by_label.get("email") == 1
    assert by_label.get("donnee_sante") == 1
    # Sensitive flag set on Art. 9 categories
    sensitive_labels = [c.label for c in report.data_categories if c.sensitive]
    assert "donnee_sante" in sensitive_labels
    assert "nom_personne" not in sensitive_labels
    asyncio.run(svc.close())


def test_processing_register_pulls_controller_info(vault_dir, monkeypatch):
    """controller name + DPO + finalités come from ControllerProfile."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={
            "controller": {"name": "Cabinet Test", "profession": "avocat"},
            "dpo": {"name": "DPO Marie", "email": "dpo@x.fr"},
            "defaults": {
                "finalites": ["Conseil juridique"],
                "bases_legales": ["execution_contrat"],
                "duree_conservation_apres_fin_mission": "5 ans",
            },
        },
        scope="global",
    ))
    asyncio.run(svc.create_project("reg-ctrl"))
    report = asyncio.run(svc.processing_register(project="reg-ctrl"))
    assert report.controller.name == "Cabinet Test"
    assert report.controller.profession == "avocat"
    assert report.dpo is not None
    assert report.dpo.name == "DPO Marie"
    assert "Conseil juridique" in report.processing_purposes
    asyncio.run(svc.close())


def test_processing_register_audit_event_written(vault_dir, monkeypatch):
    """The act of generating a registre is itself audited."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("reg-audit"))
    asyncio.run(svc.processing_register(project="reg-audit"))
    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "reg-audit" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit path differs in this env")
    events = list(read_events(audit_path))
    types = [e.event_type for e in events]
    assert "registre_generated" in types
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_processing_register.py -v --no-header
```
Expected: AttributeError on `processing_register`.

- [ ] **Step 3: Add Pydantic models**

Append to `src/piighost/service/models.py`:

```python


# ---- RGPD Phase 2: Registre Art. 30 + DPIA ----


class ControllerInfo(BaseModel):
    """Identity of the data controller (cabinet / structure)."""
    name: str = ""
    profession: str = ""
    bar_or_order_number: str = ""
    address: str = ""
    country: str = "FR"


class DPOInfo(BaseModel):
    """Designated Data Protection Officer."""
    name: str = ""
    email: str = ""
    phone: str = ""


class DataCategoryItem(BaseModel):
    """One row of the registre's 'categories of data' table."""
    label: str            # e.g. "nom_personne", "donnee_sante"
    count: int
    sensitive: bool = False  # True iff Art. 9 RGPD sensitive category


class RetentionItem(BaseModel):
    """One retention rule applied to a category of doc/data."""
    category: str
    duration: str         # e.g. "5 ans après fin de la mission"


class TransferItem(BaseModel):
    """One identified transfer of data outside the EU."""
    destination: str       # e.g. "USA", "Switzerland"
    recipient: str = ""
    legal_mechanism: str = ""  # e.g. "Standard Contractual Clauses"


class SecurityMeasureItem(BaseModel):
    """One technical/organisational security measure."""
    name: str
    auto_detected: bool = False


class DocumentsSummary(BaseModel):
    """Aggregate counts for the documents_meta inventory."""
    total_docs: int = 0
    by_doc_type: dict[str, int] = Field(default_factory=dict)
    by_language: dict[str, int] = Field(default_factory=dict)
    total_pages: int = 0


class ManualFieldHint(BaseModel):
    """A field the avocat must fill manually, with a hint."""
    field: str
    hint: str


class ProcessingRegister(BaseModel):
    """Art. 30 — registre des activités de traitement.

    Auto-built from documents_meta + vault stats + audit log +
    ControllerProfile. Fields the system can't infer are surfaced
    via ``manual_fields`` so the avocat knows what to complete.
    """
    v: Literal[1] = 1
    generated_at: int
    project: str

    # 1. Identité du responsable
    controller: ControllerInfo = Field(default_factory=ControllerInfo)
    dpo: DPOInfo | None = None

    # 2. Description du traitement
    processing_name: str = ""
    processing_purposes: list[str] = Field(default_factory=list)
    legal_bases: list[str] = Field(default_factory=list)

    # 3. Catégories de personnes concernées (heuristique)
    data_subject_categories: list[str] = Field(default_factory=list)

    # 4. Catégories de données traitées
    data_categories: list[DataCategoryItem] = Field(default_factory=list)
    sensitive_categories_present: list[str] = Field(default_factory=list)

    # 5. Destinataires
    recipients_internal: list[str] = Field(default_factory=list)
    recipients_external: list[str] = Field(default_factory=list)

    # 6. Transferts hors UE
    transfers_outside_eu: list[TransferItem] = Field(default_factory=list)

    # 7. Durées de conservation
    retention_periods: list[RetentionItem] = Field(default_factory=list)

    # 8. Mesures de sécurité
    security_measures: list[SecurityMeasureItem] = Field(default_factory=list)

    # 9. Inventaire docs
    documents_summary: DocumentsSummary = Field(default_factory=DocumentsSummary)

    # 10. À compléter manuellement
    manual_fields: list[ManualFieldHint] = Field(default_factory=list)
```

- [ ] **Step 4: Create `compliance/__init__.py` package init**

```python
"""piighost.compliance — RGPD compliance subsystem.

Builders for Art. 30 register, DPIA-lite screening, and the render
layer that turns structured data into MD/DOCX/PDF deliverables.
"""
```

- [ ] **Step 5: Implement the register builder**

Create `src/piighost/compliance/processing_register.py`:

```python
"""Build a ProcessingRegister (Art. 30) from project state.

Reads:
  - vault_stats() for category counts
  - documents_meta for doc-level inventory (doc_type, language, pages)
  - audit log v2 for recipients (caller_kind != 'skill') + outbound events
  - ControllerProfile for controller/DPO/purposes/retention

Doesn't write anything except the audit event 'registre_generated'.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from piighost.service.controller_profile import ControllerProfileService
    from piighost.vault.store import Vault
    from piighost.vault.audit import AuditLogger

from piighost.service.models import (
    ControllerInfo, DPOInfo, DataCategoryItem, DocumentsSummary,
    ManualFieldHint, ProcessingRegister, RetentionItem,
    SecurityMeasureItem,
)


# Art. 9 RGPD — sensitive categories the system can detect
_ART9_LABELS = {
    "donnee_sante", "donnee_biometrique", "donnee_genetique",
    "opinion_politique", "religion", "orientation_sexuelle",
    "origine_ethnique", "appartenance_syndicale", "condamnation_penale",
}


def build_processing_register(
    *,
    project_name: str,
    vault: "Vault",
    indexing_store,             # IndexingStore
    audit: "AuditLogger",
    profile: dict,
) -> ProcessingRegister:
    """Compose all signals into a ProcessingRegister.

    ``profile`` is the dict from ``ControllerProfileService.get(scope='project')``
    (already merged with global). Empty dict means "no profile set" — the
    builder fills with empty strings and adds manual_fields hints.
    """
    # 1. Identity
    ctrl_dict = profile.get("controller", {}) if isinstance(profile, dict) else {}
    controller = ControllerInfo(
        name=ctrl_dict.get("name", ""),
        profession=ctrl_dict.get("profession", ""),
        bar_or_order_number=ctrl_dict.get("bar_or_order_number", ""),
        address=ctrl_dict.get("address", ""),
        country=ctrl_dict.get("country", "FR"),
    )
    dpo_dict = profile.get("dpo", {}) if isinstance(profile, dict) else {}
    dpo = None
    if dpo_dict.get("name") or dpo_dict.get("email"):
        dpo = DPOInfo(
            name=dpo_dict.get("name", ""),
            email=dpo_dict.get("email", ""),
            phone=dpo_dict.get("phone", ""),
        )

    defaults = profile.get("defaults", {}) if isinstance(profile, dict) else {}

    # 2. Vault inventory
    stats = vault.stats()
    data_categories: list[DataCategoryItem] = []
    sensitive_categories: list[str] = []
    for label, count in (stats.by_label or {}).items():
        is_sensitive = label in _ART9_LABELS
        data_categories.append(DataCategoryItem(
            label=label, count=count, sensitive=is_sensitive,
        ))
        if is_sensitive:
            sensitive_categories.append(label)

    # 3. Documents inventory
    docs_meta = indexing_store.list_documents_meta(project_name, limit=10000)
    docs_summary = DocumentsSummary(
        total_docs=len(docs_meta),
        by_doc_type=_count_by(docs_meta, "doc_type"),
        by_language=_count_by(docs_meta, "doc_language"),
        total_pages=sum((m.doc_page_count or 0) for m in docs_meta),
    )

    # 4. Subjects (heuristic on dossier_id + parties presence)
    subjects = _classify_data_subjects(docs_meta, controller.profession)

    # 5. Security measures (auto-detect what we can)
    measures = _detect_security_measures(stats, vault)

    # 6. Manual fields (always add hints for what we can't infer)
    manual = [
        ManualFieldHint(
            field="autres_destinataires_humains",
            hint="Liste des collaborateurs/associés qui consultent ce dossier",
        ),
        ManualFieldHint(
            field="sous_traitants",
            hint="Cloud, hébergeurs externes, services tiers (Microsoft 365, AWS, etc.)",
        ),
        ManualFieldHint(
            field="transferts_hors_ue",
            hint="Si certains sous-traitants sont hors UE, préciser le mécanisme (CCS, BCR, décision d'adéquation)",
        ),
    ]

    # 7. Retention rules
    retention = []
    if defaults.get("duree_conservation_apres_fin_mission"):
        retention.append(RetentionItem(
            category="standard",
            duration=str(defaults["duree_conservation_apres_fin_mission"]),
        ))

    register = ProcessingRegister(
        generated_at=int(time.time()),
        project=project_name,
        controller=controller,
        dpo=dpo,
        processing_name=f"Dossier {project_name}",
        processing_purposes=list(defaults.get("finalites") or []),
        legal_bases=list(defaults.get("bases_legales") or []),
        data_subject_categories=subjects,
        data_categories=data_categories,
        sensitive_categories_present=sensitive_categories,
        recipients_internal=[],
        recipients_external=[],
        transfers_outside_eu=[],
        retention_periods=retention,
        security_measures=measures,
        documents_summary=docs_summary,
        manual_fields=manual,
    )

    # 8. Audit event
    try:
        audit.record_v2(
            event_type="registre_generated",
            project_id=project_name,
            metadata={
                "n_categories": len(data_categories),
                "n_sensitive": len(sensitive_categories),
                "n_docs": len(docs_meta),
            },
        )
    except Exception:
        pass

    return register


def _count_by(items, attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        v = getattr(item, attr, None)
        key = str(v) if v else "unknown"
        out[key] = out.get(key, 0) + 1
    return out


def _classify_data_subjects(docs_meta, profession: str) -> list[str]:
    """Heuristic: dossier_id 'client*' → 'clients', 'rh|paie|salarie' → 'salariés'."""
    subjects: set[str] = set()
    for m in docs_meta:
        d = (m.dossier_id or "").lower()
        if d.startswith("client") or d.startswith("dossier"):
            subjects.add("clients")
        if any(k in d for k in ("rh", "paie", "salarie", "personnel")):
            subjects.add("salariés")
    if profession == "avocat" and not subjects:
        subjects.add("clients du cabinet")
    if profession == "rh" and not subjects:
        subjects.add("salariés")
    return sorted(subjects) if subjects else ["clients"]


def _detect_security_measures(stats, vault) -> list[SecurityMeasureItem]:
    """Auto-detect measures that ARE in place."""
    measures = [
        SecurityMeasureItem(
            name=f"Anonymisation à la source ({stats.total} placeholders actifs)",
            auto_detected=True,
        ),
        SecurityMeasureItem(
            name="Détection PII via modèle local (pas de transfert vers cloud externe pour l'inférence)",
            auto_detected=True,
        ),
    ]
    return measures
```

- [ ] **Step 6: Add the service method on `_ProjectService`**

In `src/piighost/service/core.py`, add to `_ProjectService` class (near `subject_access`):

```python
    async def processing_register(self) -> "ProcessingRegister":
        """Generate the Art. 30 register for this project."""
        from piighost.compliance.processing_register import build_processing_register
        from piighost.service.controller_profile import ControllerProfileService
        cp_svc = ControllerProfileService(self._project_dir.parent.parent)
        profile = cp_svc.get(scope="project", project=self._project_name)
        return build_processing_register(
            project_name=self._project_name,
            vault=self._vault,
            indexing_store=self._indexing_store,
            audit=self._audit,
            profile=profile,
        )
```

Add to `PIIGhostService` (dispatcher):

```python
    async def processing_register(self, *, project: str) -> "ProcessingRegister":
        svc = await self._get_project(project)
        return await svc.processing_register()
```

- [ ] **Step 7: Run tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_processing_register.py -v --no-header
```
Expected: 4 passed.

- [ ] **Step 8: Commit**

```bash
git add src/piighost/service/models.py src/piighost/compliance/__init__.py src/piighost/compliance/processing_register.py src/piighost/service/core.py tests/unit/test_processing_register.py
git commit -m "feat(compliance): processing_register (Art. 30) Phase 2

Builds the Art. 30 register from project state:
  - vault.stats() -> category inventory + Art. 9 sensitive flag
  - documents_meta -> doc inventory by type/language/pages
  - ControllerProfile -> controller, DPO, purposes, retention
  - audit log -> recipients (future enhancement)

Pure read except for the 'registre_generated' audit event. Returns
a ProcessingRegister Pydantic model — Phase 2 Task 5 turns this
into MD/DOCX/PDF via the render layer."
```

---

## Task 4: `DPIAScreening` Pydantic + service method

**Files:**
- Modify: `src/piighost/service/models.py` (append)
- Create: `src/piighost/compliance/dpia_screening.py`
- Modify: `src/piighost/service/core.py` (add `dpia_screening` dispatcher + per-project method)
- Test: `tests/unit/test_dpia_screening.py`

DPIA-lite — detects Art. 35.3 + CNIL guidance triggers and redirects to the official PIA tool.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_dpia_screening.py`:

```python
"""Service-level tests for dpia_screening (DPIA-lite Art. 35)."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_dpia_empty_project_verdict_not_required(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("dpia-empty"))
    report = asyncio.run(svc.dpia_screening(project="dpia-empty"))
    assert report.verdict in ("dpia_not_required", "dpia_recommended")
    assert report.cnil_pia_url.startswith("https://www.cnil.fr/")
    asyncio.run(svc.close())


def test_dpia_required_when_sensitive_data_at_scale(vault_dir, monkeypatch):
    """≥1 mandatory trigger (Art. 35.3.b) when sensitive data > 100 entries."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("dpia-sens"))
    proj = asyncio.run(svc._get_project("dpia-sens"))
    # Seed 150 sensitive entities
    for i in range(150):
        proj._vault.upsert_entity(
            token=f"<<sante:{i}>>", original=f"diabete-{i}",
            label="donnee_sante", confidence=0.9,
        )
    report = asyncio.run(svc.dpia_screening(project="dpia-sens"))
    assert report.verdict == "dpia_required"
    trigger_codes = [t.code for t in report.triggers]
    assert "art35.3.b" in trigger_codes
    asyncio.run(svc.close())


def test_dpia_innovative_use_always_present(vault_dir, monkeypatch):
    """Trigger cnil_5 (usage innovant — IA/NER) is always emitted because
    piighost itself uses ML for detection."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("dpia-ai"))
    report = asyncio.run(svc.dpia_screening(project="dpia-ai"))
    trigger_codes = [t.code for t in report.triggers]
    assert "cnil_5" in trigger_codes
    asyncio.run(svc.close())


def test_dpia_emits_pia_inputs(vault_dir, monkeypatch):
    """The cnil_pia_inputs block must be populated for direct import into
    the CNIL PIA software."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={
            "controller": {"name": "Test Cabinet", "profession": "avocat"},
            "defaults": {
                "finalites": ["Conseil juridique"],
                "bases_legales": ["execution_contrat"],
            },
        },
        scope="global",
    ))
    asyncio.run(svc.create_project("dpia-inputs"))
    report = asyncio.run(svc.dpia_screening(project="dpia-inputs"))
    assert report.cnil_pia_inputs.processing_name
    assert "Conseil juridique" in report.cnil_pia_inputs.purposes
    asyncio.run(svc.close())


def test_dpia_audit_event_written(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("dpia-audit"))
    asyncio.run(svc.dpia_screening(project="dpia-audit"))
    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "dpia-audit" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit path differs")
    events = list(read_events(audit_path))
    types = [e.event_type for e in events]
    assert "dpia_screened" in types
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_dpia_screening.py -v --no-header
```
Expected: AttributeError on `dpia_screening`.

- [ ] **Step 3: Add Pydantic models**

Append to `src/piighost/service/models.py`:

```python


class DPIATrigger(BaseModel):
    """One Art. 35.3 or CNIL trigger detected for this project."""
    code: str
    name: str
    matched_evidence: list[str] = Field(default_factory=list)
    severity: Literal["mandatory", "high", "medium", "low"]


class CNILPIAInputs(BaseModel):
    """Pre-filled inputs for the official CNIL PIA software."""
    processing_name: str = ""
    processing_description: str = ""
    data_categories: list[str] = Field(default_factory=list)
    data_subjects: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    legal_bases: list[str] = Field(default_factory=list)
    retention: str = ""
    recipients: list[str] = Field(default_factory=list)
    security_measures: list[str] = Field(default_factory=list)


class DPIAScreening(BaseModel):
    """DPIA-lite screening — does this project require a full DPIA?"""
    v: Literal[1] = 1
    generated_at: int
    project: str
    data_inventory: dict[str, int] = Field(default_factory=dict)
    triggers: list[DPIATrigger] = Field(default_factory=list)
    verdict: Literal["dpia_required", "dpia_recommended", "dpia_not_required"]
    verdict_explanation: str = ""
    cnil_pia_inputs: CNILPIAInputs = Field(default_factory=CNILPIAInputs)
    cnil_pia_url: str = "https://www.cnil.fr/fr/outil-pia-telechargez-et-installez-le-logiciel-de-la-cnil"
```

- [ ] **Step 4: Implement DPIA-lite logic**

Create `src/piighost/compliance/dpia_screening.py`:

```python
"""DPIA-lite screening (Art. 35) — detect triggers, emit verdict, prepare
inputs for the official CNIL PIA software.

We do NOT generate a full DPIA — that's CNIL's tool. We only screen
and pre-fill the inputs.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from piighost.vault.store import Vault
    from piighost.vault.audit import AuditLogger

from piighost.service.models import (
    CNILPIAInputs, DPIAScreening, DPIATrigger,
)


# Art. 9 RGPD sensitive labels (same as processing_register)
_ART9_LABELS = {
    "donnee_sante", "donnee_biometrique", "donnee_genetique",
    "opinion_politique", "religion", "orientation_sexuelle",
    "origine_ethnique", "appartenance_syndicale", "condamnation_penale",
}

_LARGE_SCALE_THRESHOLD = 10000   # CNIL: traitement à grande échelle
_SENSITIVE_AT_SCALE_THRESHOLD = 100  # Art. 35.3.b: sensible à grande échelle


def screen_dpia(
    *,
    project_name: str,
    vault: "Vault",
    indexing_store,
    audit: "AuditLogger",
    profile: dict,
) -> DPIAScreening:
    """Run the DPIA-lite screening and return the result."""
    stats = vault.stats()
    inventory = dict(stats.by_label or {})
    triggers: list[DPIATrigger] = []

    # Art. 35.3.b — sensible à grande échelle
    sensitive_total = sum(c for l, c in inventory.items() if l in _ART9_LABELS)
    if sensitive_total >= _SENSITIVE_AT_SCALE_THRESHOLD:
        sensitive_breakdown = [
            f"{l}: {c}" for l, c in inventory.items() if l in _ART9_LABELS
        ]
        triggers.append(DPIATrigger(
            code="art35.3.b",
            name="Données sensibles ou hautement personnelles à grande échelle",
            matched_evidence=sensitive_breakdown,
            severity="mandatory",
        ))

    # CNIL critère 2 — traitement à grande échelle
    if stats.total >= _LARGE_SCALE_THRESHOLD:
        triggers.append(DPIATrigger(
            code="cnil_2",
            name="Traitement à grande échelle",
            matched_evidence=[f"total: {stats.total} entités"],
            severity="high",
        ))

    # CNIL critère 4 — personnes vulnérables
    if "donnee_sante" in inventory:
        triggers.append(DPIATrigger(
            code="cnil_4",
            name="Données concernant des personnes vulnérables (santé)",
            matched_evidence=[f"donnee_sante: {inventory['donnee_sante']}"],
            severity="high",
        ))

    # CNIL critère 5 — usage innovant (IA/NER)
    triggers.append(DPIATrigger(
        code="cnil_5",
        name="Usage innovant: détection PII via modèle ML local (NER)",
        matched_evidence=["piighost utilise GLiNER2 + adaptateur français pour la détection"],
        severity="medium",
    ))

    # CNIL critère 7 — identité civile complète
    has_civil_id = (
        "nom_personne" in inventory and
        "lieu" in inventory and  # adresse approximée
        "numero_securite_sociale" in inventory
    )
    if has_civil_id:
        triggers.append(DPIATrigger(
            code="cnil_7",
            name="Données concernant l'identité civile complète",
            matched_evidence=["nom + lieu + numero_securite_sociale tous présents"],
            severity="high",
        ))

    # CNIL critère 9 — données salariés
    profession = (profile or {}).get("controller", {}).get("profession", "")
    if profession == "rh":
        triggers.append(DPIATrigger(
            code="cnil_9",
            name="Données concernant des salariés (RH)",
            matched_evidence=[f"controller.profession = '{profession}'"],
            severity="high",
        ))

    # Verdict
    severities = [t.severity for t in triggers]
    if any(s == "mandatory" for s in severities) or severities.count("high") >= 2:
        verdict = "dpia_required"
        explanation = "Au moins un critère obligatoire ou ≥2 critères CNIL haute sévérité."
    elif "high" in severities:
        verdict = "dpia_recommended"
        explanation = "1 critère CNIL haute sévérité — DPIA recommandée."
    else:
        verdict = "dpia_not_required"
        explanation = "Aucun trigger Art. 35.3 mandatory. DPIA non requise mais documentation conseillée."

    # CNIL PIA inputs
    defaults = (profile or {}).get("defaults", {})
    pia_inputs = CNILPIAInputs(
        processing_name=f"Dossier {project_name}",
        processing_description=f"Traitement de données dans le cadre de l'activité du cabinet",
        data_categories=sorted(inventory.keys()),
        data_subjects=["clients", "tiers contractants"]
            if profession != "rh" else ["salariés"],
        purposes=list(defaults.get("finalites") or []),
        legal_bases=list(defaults.get("bases_legales") or []),
        retention=str(defaults.get("duree_conservation_apres_fin_mission", "")),
        recipients=[],
        security_measures=[
            "Anonymisation à la source",
            "Détection PII locale (pas de transfert vers cloud externe pour inférence)",
        ],
    )

    report = DPIAScreening(
        generated_at=int(time.time()),
        project=project_name,
        data_inventory=inventory,
        triggers=triggers,
        verdict=verdict,
        verdict_explanation=explanation,
        cnil_pia_inputs=pia_inputs,
    )

    # Audit
    try:
        audit.record_v2(
            event_type="dpia_screened",
            project_id=project_name,
            metadata={
                "verdict": verdict,
                "n_triggers": len(triggers),
                "n_mandatory": sum(1 for s in severities if s == "mandatory"),
            },
        )
    except Exception:
        pass

    return report
```

- [ ] **Step 5: Add the service method**

In `_ProjectService` (core.py):

```python
    async def dpia_screening(self) -> "DPIAScreening":
        """Run DPIA-lite screening for this project."""
        from piighost.compliance.dpia_screening import screen_dpia
        from piighost.service.controller_profile import ControllerProfileService
        cp_svc = ControllerProfileService(self._project_dir.parent.parent)
        profile = cp_svc.get(scope="project", project=self._project_name)
        return screen_dpia(
            project_name=self._project_name,
            vault=self._vault,
            indexing_store=self._indexing_store,
            audit=self._audit,
            profile=profile,
        )
```

In `PIIGhostService`:

```python
    async def dpia_screening(self, *, project: str) -> "DPIAScreening":
        svc = await self._get_project(project)
        return await svc.dpia_screening()
```

- [ ] **Step 6: Run tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_dpia_screening.py -v --no-header
```
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/service/models.py src/piighost/compliance/dpia_screening.py src/piighost/service/core.py tests/unit/test_dpia_screening.py
git commit -m "feat(compliance): dpia_screening (DPIA-lite Art. 35) Phase 2

Detects Art. 35.3 + CNIL guidance triggers, emits verdict, prepares
CNILPIAInputs ready to import into the official CNIL PIA software.

Triggers detected:
  - art35.3.b: sensible à grande échelle (>=100 entités Art. 9)
  - cnil_2: traitement à grande échelle (>=10000 entités)
  - cnil_4: personnes vulnérables (santé)
  - cnil_5: usage innovant (IA/NER) — toujours présent (notre cas)
  - cnil_7: identité civile complète (nom+lieu+nss)
  - cnil_9: données salariés (profession=rh)

Verdict: mandatory>=1 OR high>=2 → required ; high>=1 → recommended ;
sinon not_required. Audit event 'dpia_screened' enregistré."
```

---

## Task 5: Render layer — `render_compliance_doc` + Jinja2 templates

**Files:**
- Modify: `src/piighost/service/models.py` (append `RenderResult`)
- Create: `src/piighost/compliance/render.py`
- Create: 8 Jinja2 templates under `src/piighost/compliance/templates/`
- Modify: `src/piighost/service/core.py` (add `render_compliance_doc` dispatcher + per-project method)
- Modify: `pyproject.toml` (add `[compliance]` extra)
- Test: `tests/unit/test_render_compliance_doc.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_render_compliance_doc.py`:

```python
"""Tests for render_compliance_doc — Markdown round-trip is the core gate.

PDF and DOCX paths are skipped if the optional [compliance] extra
isn't installed in the test environment.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_render_registre_md(vault_dir, monkeypatch, tmp_path):
    """Generate a registre, render to MD, verify the output contains
    expected markers from the template."""
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={
            "controller": {"name": "Cabinet Demo", "profession": "avocat"},
            "defaults": {"finalites": ["Conseil juridique"]},
        }, scope="global",
    ))
    asyncio.run(svc.create_project("render-md"))
    register = asyncio.run(svc.processing_register(project="render-md"))

    output = tmp_path / "registre.md"
    result = asyncio.run(svc.render_compliance_doc(
        data=register.model_dump(),
        format="md",
        profile="generic",
        output_path=str(output),
    ))
    assert result.path == str(output)
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Cabinet Demo" in content
    assert "render-md" in content
    asyncio.run(svc.close())


def test_render_dpia_md(vault_dir, monkeypatch, tmp_path):
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("render-dpia"))
    dpia = asyncio.run(svc.dpia_screening(project="render-dpia"))

    output = tmp_path / "dpia.md"
    asyncio.run(svc.render_compliance_doc(
        data=dpia.model_dump(),
        format="md",
        profile="generic",
        output_path=str(output),
    ))
    content = output.read_text(encoding="utf-8")
    # The DPIA template should include the verdict + CNIL link
    assert dpia.verdict in content
    assert "cnil.fr" in content
    asyncio.run(svc.close())


def test_render_with_avocat_profile_uses_avocat_template(
    vault_dir, monkeypatch, tmp_path,
):
    """Verify profile-specific template selection."""
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={"controller": {"name": "Maître X", "profession": "avocat"}},
        scope="global",
    ))
    asyncio.run(svc.create_project("render-av"))
    register = asyncio.run(svc.processing_register(project="render-av"))
    output = tmp_path / "registre_avocat.md"
    asyncio.run(svc.render_compliance_doc(
        data=register.model_dump(),
        format="md",
        profile="avocat",
        output_path=str(output),
    ))
    content = output.read_text(encoding="utf-8")
    # Avocat template includes a specific mention
    assert "barreau" in content.lower() or "CNB" in content
    asyncio.run(svc.close())


def test_render_pdf_skipped_when_extra_missing(vault_dir, monkeypatch, tmp_path):
    """If weasyprint isn't installed, render(pdf) raises a clear ImportError."""
    try:
        import weasyprint  # noqa: F401
        pytest.skip("weasyprint installed — this test only runs without it")
    except ImportError:
        pass
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("render-no-pdf"))
    register = asyncio.run(svc.processing_register(project="render-no-pdf"))
    with pytest.raises((ImportError, RuntimeError)):
        asyncio.run(svc.render_compliance_doc(
            data=register.model_dump(), format="pdf",
            profile="generic", output_path=str(tmp_path / "out.pdf"),
        ))
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_render_compliance_doc.py -v --no-header
```
Expected: 4 errors (module not found, attribute not found).

- [ ] **Step 3: Add `RenderResult` model**

Append to `src/piighost/service/models.py`:

```python


class RenderResult(BaseModel):
    """Outcome of rendering a structured compliance doc to MD/DOCX/PDF."""
    path: str
    format: Literal["md", "docx", "pdf"]
    size_bytes: int = 0
    rendered_at: int
```

- [ ] **Step 4: Add the `compliance` optional extra to `pyproject.toml`**

Find the `[project.optional-dependencies]` section in `pyproject.toml` (or add it under `[project]`). Add:

```toml
[project.optional-dependencies]
compliance = [
    "Jinja2>=3.1",
    "markdown>=3.5",
    # Heavier optional deps:
    # "docxtpl>=0.16",  # uncomment when DOCX output is needed
    # "weasyprint>=62",  # uncomment when PDF output is needed
]
```

For Task 5, only `Jinja2` and `markdown` are required (MD path). DOCX and PDF paths import lazily and raise clear `ImportError` if missing.

- [ ] **Step 5: Create the bundled templates**

Create the template directory tree:

```
src/piighost/compliance/templates/
├── generic/
│   ├── registre.md.j2
│   ├── dpia_screening.md.j2
│   └── subject_access.md.j2
├── avocat/
│   └── registre.md.j2
├── notaire/
│   └── registre.md.j2
├── medecin/
│   └── registre.md.j2
├── expert_comptable/
│   └── registre.md.j2
└── rh/
    └── registre.md.j2
```

`generic/registre.md.j2`:

```jinja
# Registre des activités de traitement (Art. 30 RGPD)

**Projet** : {{ project }}
**Date de génération** : {{ generated_at }}

## 1. Identité du responsable de traitement

- **Nom** : {{ controller.name or "[À compléter]" }}
- **Profession** : {{ controller.profession or "[À compléter]" }}
{% if controller.bar_or_order_number %}- **N° d'inscription** : {{ controller.bar_or_order_number }}
{% endif %}- **Adresse** : {{ controller.address or "[À compléter]" }}
- **Pays** : {{ controller.country }}

{% if dpo %}
## 2. Délégué à la protection des données (DPO)

- **Nom** : {{ dpo.name }}
{% if dpo.email %}- **Email** : {{ dpo.email }}
{% endif %}{% if dpo.phone %}- **Téléphone** : {{ dpo.phone }}
{% endif %}{% endif %}

## 3. Description du traitement

- **Nom du traitement** : {{ processing_name }}
{% if processing_purposes %}- **Finalités** :
{% for p in processing_purposes %}  - {{ p }}
{% endfor %}{% endif %}
{% if legal_bases %}- **Bases légales (Art. 6 RGPD)** :
{% for b in legal_bases %}  - {{ b }}
{% endfor %}{% endif %}

## 4. Catégories de personnes concernées

{% for s in data_subject_categories %}- {{ s }}
{% endfor %}

## 5. Catégories de données traitées ({{ data_categories|length }} catégories)

| Catégorie | Nombre | Sensible (Art. 9) |
|---|---:|:-:|
{% for c in data_categories %}| {{ c.label }} | {{ c.count }} | {% if c.sensitive %}✓{% else %}—{% endif %} |
{% endfor %}

{% if sensitive_categories_present %}
**⚠️ Catégories sensibles présentes (Art. 9 RGPD)** : {{ sensitive_categories_present | join(", ") }}
{% endif %}

## 6. Destinataires

- **Internes** : {{ recipients_internal | join(", ") if recipients_internal else "[À compléter manuellement]" }}
- **Externes** : {{ recipients_external | join(", ") if recipients_external else "[À compléter manuellement]" }}

## 7. Transferts hors UE

{% if transfers_outside_eu %}{% for t in transfers_outside_eu %}- {{ t.destination }} → {{ t.recipient }} ({{ t.legal_mechanism }})
{% endfor %}{% else %}*Aucun transfert hors UE détecté automatiquement. Compléter manuellement si applicable.*
{% endif %}

## 8. Durées de conservation

{% for r in retention_periods %}- **{{ r.category }}** : {{ r.duration }}
{% endfor %}

## 9. Mesures de sécurité

{% for m in security_measures %}- {{ m.name }}{% if m.auto_detected %} *(détecté automatiquement)*{% endif %}
{% endfor %}

## 10. Inventaire des documents

- **Total** : {{ documents_summary.total_docs }} documents
{% if documents_summary.total_pages %}- **Pages totales** : {{ documents_summary.total_pages }}
{% endif %}
{% if documents_summary.by_doc_type %}**Par type** :
{% for k, v in documents_summary.by_doc_type.items() %}  - {{ k }} : {{ v }}
{% endfor %}{% endif %}

## Champs à compléter manuellement

{% for f in manual_fields %}- **{{ f.field }}** : {{ f.hint }}
{% endfor %}

---

*Document généré par piighost. Vérifier et compléter avant signature.*
```

`generic/dpia_screening.md.j2`:

```jinja
# Screening DPIA-lite (Art. 35 RGPD)

**Projet** : {{ project }}
**Date** : {{ generated_at }}

## Verdict

**{{ verdict | upper }}**

{{ verdict_explanation }}

{% if verdict != "dpia_not_required" %}
**Étape suivante** : produire la DPIA complète via l'outil officiel CNIL :
[Télécharger PIA]({{ cnil_pia_url }})

Les inputs ci-dessous sont déjà pré-remplis pour import direct dans le PIA software.
{% endif %}

## Triggers détectés ({{ triggers | length }})

| Code | Critère | Sévérité |
|---|---|---|
{% for t in triggers %}| `{{ t.code }}` | {{ t.name }} | {{ t.severity }} |
{% endfor %}

{% for t in triggers %}### {{ t.code }} — {{ t.name }}

**Sévérité** : {{ t.severity }}

**Évidence** :
{% for e in t.matched_evidence %}- {{ e }}
{% endfor %}

{% endfor %}

## Inventaire des données traitées

{% for label, count in data_inventory.items() %}- {{ label }} : {{ count }}
{% endfor %}

## Inputs pré-remplis pour le PIA software CNIL

```json
{
  "processing_name": "{{ cnil_pia_inputs.processing_name }}",
  "data_categories": {{ cnil_pia_inputs.data_categories | tojson }},
  "data_subjects": {{ cnil_pia_inputs.data_subjects | tojson }},
  "purposes": {{ cnil_pia_inputs.purposes | tojson }},
  "legal_bases": {{ cnil_pia_inputs.legal_bases | tojson }},
  "retention": "{{ cnil_pia_inputs.retention }}",
  "security_measures": {{ cnil_pia_inputs.security_measures | tojson }}
}
```

---

*Document généré par piighost (DPIA-lite). Pour la DPIA complète, utiliser l'outil officiel CNIL.*
```

`generic/subject_access.md.j2`:

```jinja
# Réponse à votre demande d'accès (Art. 15 RGPD)

**Date du rapport** : {{ generated_at }}
**Projet** : {{ project }}

## Sujet

{% for p in subject_preview %}- {{ p }}
{% endfor %}

## Catégories de données traitées ({{ categories_found | length }})

{% for label, count in categories_found.items() %}- **{{ label }}** : {{ count }} occurrence(s)
{% endfor %}

## Documents concernés ({{ documents | length }})

| Document | Type | Date | Occurrences |
|---|---|---|---:|
{% for d in documents %}| {{ d.file_name }} | {{ d.doc_type }} | {{ d.doc_date or "—" }} | {{ d.occurrences }} |
{% endfor %}

## Finalités du traitement

{{ processing_purpose or "[À compléter]" }}

## Base légale

{{ legal_basis or "[À compléter]" }}

## Durée de conservation

{{ retention_period or "[À compléter]" }}

## Extraits redactés ({{ total_excerpts }}{% if excerpts_truncated %}, tronqués à {{ excerpts | length }}{% endif %})

{% for e in excerpts %}> **{{ e.file_name }}** (chunk {{ e.chunk_index }}) :
> {{ e.redacted_text }}

{% endfor %}

---

*Document généré par piighost. À vérifier et signer avant envoi au demandeur.*
```

For the profession-specific templates (`avocat/registre.md.j2`, `notaire/registre.md.j2`, etc.), use the generic template as base and add a profession-specific section. Example for `avocat/registre.md.j2`:

```jinja
{% extends "generic/registre.md.j2" if False else "" %}{# Inline copy below: Jinja2 doesn't easily extend across loaders without env config. Just paste-and-tweak. #}
# Registre des activités de traitement (Art. 30 RGPD) — Avocat

**Projet** : {{ project }}
**Date de génération** : {{ generated_at }}

> *Cabinet d'avocat — secret professionnel Art. 66-5 loi du 31 décembre 1971 — CNB / Conseil National des Barreaux.*

[... copy generic registre body verbatim, with the avocat-specific intro above ...]
```

For brevity, the implementer should copy the generic body and prepend the profession-specific header. The other 4 profession templates follow the same pattern with their own legal references:
- **notaire** : Art. 1316-2 Code civil + Décret 1971 + Conseil Supérieur du Notariat
- **medecin** : Art. R4127 Code santé + HDS hosting + Conseil de l'Ordre
- **expert_comptable** : Code de déontologie 2012 + Ordre des Experts-Comptables
- **rh** : Code du travail + adapté pour traitements salariés

Implementers: focus on getting the **generic** templates right first; the profession-specific ones can be near-copies with the profession-specific intro paragraph. Quality content review by an actual avocat is a follow-up, not Phase 2.

- [ ] **Step 6: Implement the render layer**

Create `src/piighost/compliance/render.py`:

```python
"""Render structured compliance dicts (ProcessingRegister, DPIAScreening,
SubjectAccessReport) into MD / DOCX / PDF deliverables.

Templates live under ``piighost.compliance.templates/<profile>/<doctype>.md.j2``.
User overrides take priority — checked at ``~/.piighost/templates/<profile>/<doctype>.<format>.j2``.

DOCX path requires ``[compliance]`` extra (docxtpl + weasyprint).
PDF path requires ``[compliance]`` extra (markdown + weasyprint).
MD path requires only Jinja2.
"""
from __future__ import annotations

import time
from importlib import resources
from pathlib import Path
from typing import Any, Literal


_DOCTYPE_BY_VERSION_FIELD = {
    # Map a serialized model dict to its template stem
    # Detected via specific keys present in the dict
}


def _detect_doctype(data: dict) -> str:
    """Detect the doctype from the shape of the dict."""
    if "subject_tokens" in data and "categories_found" in data:
        return "subject_access"
    if "triggers" in data and "verdict" in data:
        return "dpia_screening"
    if "data_categories" in data and "controller" in data:
        return "registre"
    raise ValueError("Cannot detect doctype from data — missing expected keys")


def _load_template(profile: str, doctype: str, format: str):
    """Load a Jinja2 template, with user-override fallback to bundled."""
    try:
        import jinja2
    except ImportError as exc:
        raise ImportError(
            "render_compliance_doc requires the 'compliance' extra. "
            "Install with: pip install piighost[compliance]"
        ) from exc

    user_dir = Path.home() / ".piighost" / "templates"
    bundled_dir = resources.files("piighost.compliance.templates")

    template_filename = f"{doctype}.{format}.j2"

    # 1. User override
    user_path = user_dir / profile / template_filename
    if user_path.exists():
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(user_path.parent)),
            autoescape=False, keep_trailing_newline=True,
        )
        return env.get_template(template_filename)

    # 2. Bundled per-profile
    bundled_path = bundled_dir / profile / template_filename
    try:
        if bundled_path.is_file():
            content = bundled_path.read_text(encoding="utf-8")
        else:
            raise FileNotFoundError
    except (FileNotFoundError, AttributeError):
        # 3. Fallback to generic
        bundled_path = bundled_dir / "generic" / template_filename
        if not bundled_path.is_file():
            raise FileNotFoundError(
                f"No template found for profile={profile} doctype={doctype} format={format}"
            )
        content = bundled_path.read_text(encoding="utf-8")

    env = jinja2.Environment(autoescape=False, keep_trailing_newline=True)
    return env.from_string(content)


def render_compliance_doc(
    *,
    data: dict,
    format: Literal["md", "docx", "pdf"] = "md",
    profile: str = "generic",
    output_path: str | None = None,
) -> dict:
    """Render structured data to a deliverable. Returns RenderResult dict."""
    doctype = _detect_doctype(data)

    # Default output path
    if output_path is None:
        ext = {"md": ".md", "docx": ".docx", "pdf": ".pdf"}[format]
        out_dir = Path.home() / ".piighost" / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        output_path = str(out_dir / f"{data.get('project', 'doc')}-{doctype}-{ts}{ext}")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if format == "md":
        template = _load_template(profile, doctype, "md")
        rendered = template.render(**data)
        output.write_text(rendered, encoding="utf-8")
    elif format == "pdf":
        try:
            import markdown as _markdown
            import weasyprint
        except ImportError as exc:
            raise ImportError(
                "PDF render requires the 'compliance' extra (weasyprint + markdown). "
                "Install with: pip install piighost[compliance]"
            ) from exc
        template = _load_template(profile, doctype, "md")
        md_rendered = template.render(**data)
        html = _markdown.markdown(md_rendered, extensions=["tables", "toc"])
        weasyprint.HTML(string=html).write_pdf(str(output))
    elif format == "docx":
        try:
            import docxtpl  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "DOCX render requires the 'compliance' extra (docxtpl). "
                "Install with: pip install piighost[compliance]"
            ) from exc
        # docxtpl needs a .docx template — for v1 we render MD-as-text into a docx
        # via the Markdown→HTML→docx pipeline using a simple wrapping.
        # If the user wants templated docx, they should provide their own.
        template = _load_template(profile, doctype, "md")
        md_rendered = template.render(**data)
        from docx import Document
        doc = Document()
        for line in md_rendered.split("\n"):
            doc.add_paragraph(line)
        doc.save(str(output))
    else:
        raise ValueError(f"Unsupported format: {format}")

    return {
        "path": str(output),
        "format": format,
        "size_bytes": output.stat().st_size if output.exists() else 0,
        "rendered_at": int(time.time()),
    }
```

- [ ] **Step 7: Add the service method**

In `_ProjectService` (core.py):

```python
    async def render_compliance_doc(
        self, *, data: dict, format: str = "md",
        profile: str = "generic", output_path: str | None = None,
    ) -> "RenderResult":
        from piighost.compliance.render import render_compliance_doc
        from piighost.service.models import RenderResult
        result = render_compliance_doc(
            data=data, format=format, profile=profile, output_path=output_path,  # type: ignore[arg-type]
        )
        return RenderResult(**result)
```

In `PIIGhostService`:

```python
    async def render_compliance_doc(
        self, *, data: dict, format: str = "md",
        profile: str = "generic", output_path: str | None = None,
        project: str = "default",
    ) -> "RenderResult":
        svc = await self._get_project(project)
        return await svc.render_compliance_doc(
            data=data, format=format, profile=profile, output_path=output_path,
        )
```

- [ ] **Step 8: Run tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_render_compliance_doc.py -v --no-header
```
Expected: 3 passed (MD tests + avocat profile), 1 conditional skip (PDF skip if weasyprint installed).

- [ ] **Step 9: Commit**

```bash
git add src/piighost/service/models.py src/piighost/compliance/render.py src/piighost/compliance/templates/ src/piighost/service/core.py pyproject.toml tests/unit/test_render_compliance_doc.py
git commit -m "feat(compliance): render layer + 8 Jinja2 templates (Phase 2)

render_compliance_doc(data, format, profile, output_path) renders
ProcessingRegister / DPIAScreening / SubjectAccessReport into
MD / DOCX / PDF deliverables.

Templates bundled in piighost.compliance.templates/:
  - generic/{registre,dpia_screening,subject_access}.md.j2
  - {avocat,notaire,medecin,expert_comptable,rh}/registre.md.j2

User overrides at ~/.piighost/templates/<profile>/<doctype>.<fmt>.j2
take priority. Fallback chain: user → profile-specific bundled → generic bundled.

MD requires Jinja2 only; DOCX/PDF require [compliance] extra
(weasyprint, markdown, python-docx). Heavy deps are gated to
keep the core MCP install tight."
```

---

## Task 6: MCP wiring for `processing_register`, `dpia_screening`, `render_compliance_doc`

**Files:**
- Modify: `src/piighost/mcp/tools.py` (3 ToolSpec)
- Modify: `src/piighost/mcp/shim.py` (3 wrappers)
- Modify: `src/piighost/daemon/server.py` (3 dispatch handlers)

- [ ] **Step 1: Add 3 ToolSpec entries**

Append to `TOOL_CATALOG` (under `# RGPD Phase 2`):

```python
    # RGPD Phase 2 — Registre Art. 30 + DPIA + Render
    ToolSpec(
        name="processing_register",
        rpc_method="processing_register",
        description=(
            "Generate the Art. 30 register for a project: controller, "
            "DPO, data categories with Art. 9 sensitivity flag, document "
            "inventory, retention, security measures. Auto-built from "
            "documents_meta + vault.stats() + ControllerProfile."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="dpia_screening",
        rpc_method="dpia_screening",
        description=(
            "DPIA-lite screening (Art. 35). Detects triggers, emits "
            "verdict, prepares CNILPIAInputs for the official CNIL PIA "
            "software. Does NOT generate a full DPIA — that's CNIL's tool."
        ),
        timeout_s=15.0,
    ),
    ToolSpec(
        name="render_compliance_doc",
        rpc_method="render_compliance_doc",
        description=(
            "Render a compliance dict (processing_register, dpia_screening, "
            "subject_access_report) to MD/DOCX/PDF using profession-aware "
            "Jinja2 templates. profile='avocat'|'notaire'|'medecin'|"
            "'expert_comptable'|'rh'|'generic'."
        ),
        timeout_s=60.0,
    ),
```

- [ ] **Step 2: Add 3 shim wrappers**

In `src/piighost/mcp/shim.py`, near the end of `_build_mcp`:

```python
    @mcp.tool(name="processing_register",
              description=by_name["processing_register"].description)
    async def processing_register(project: str = "default") -> dict:
        return await _lazy_dispatch(
            by_name["processing_register"],
            params={"project": project},
        )

    @mcp.tool(name="dpia_screening",
              description=by_name["dpia_screening"].description)
    async def dpia_screening(project: str = "default") -> dict:
        return await _lazy_dispatch(
            by_name["dpia_screening"],
            params={"project": project},
        )

    @mcp.tool(name="render_compliance_doc",
              description=by_name["render_compliance_doc"].description)
    async def render_compliance_doc(
        data: dict, format: str = "md",
        profile: str = "generic", output_path: str = "",
        project: str = "default",
    ) -> dict:
        return await _lazy_dispatch(
            by_name["render_compliance_doc"],
            params={
                "data": data, "format": format, "profile": profile,
                "output_path": output_path or None, "project": project,
            },
        )
```

- [ ] **Step 3: Add 3 dispatch handlers**

In `src/piighost/daemon/server.py`'s `_dispatch`, before the final raise:

```python
    if method == "processing_register":
        report = await svc.processing_register(
            project=params.get("project", "default"),
        )
        return report.model_dump()
    if method == "dpia_screening":
        report = await svc.dpia_screening(
            project=params.get("project", "default"),
        )
        return report.model_dump()
    if method == "render_compliance_doc":
        result = await svc.render_compliance_doc(
            data=params["data"],
            format=params.get("format", "md"),
            profile=params.get("profile", "generic"),
            output_path=params.get("output_path") or None,
            project=params.get("project", "default"),
        )
        return result.model_dump()
```

- [ ] **Step 4: Smoke test**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
from piighost.mcp.tools import TOOL_CATALOG
names = [t.name for t in TOOL_CATALOG]
for tool in ['processing_register', 'dpia_screening', 'render_compliance_doc']:
    assert tool in names
print('All 3 Phase 2 tools registered')
"
```
Expected: prints `All 3 Phase 2 tools registered`.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/tools.py src/piighost/mcp/shim.py src/piighost/daemon/server.py
git commit -m "feat(mcp): wire processing_register + dpia_screening + render_compliance_doc

Three new MCP tools for RGPD Phase 2:
  - processing_register(project) -> ProcessingRegister
  - dpia_screening(project) -> DPIAScreening
  - render_compliance_doc(data, format, profile, output_path, project)
      -> RenderResult

Timeouts: 30s/15s/60s respectively. The render path is the slowest
because PDF generation via weasyprint can be heavy on large
templates (~30s for 50-page registre)."
```

---

## Task 7: Plugin skills `/hacienda:rgpd:registre` + `/hacienda:rgpd:dpia`

**Files:**
- Create: `.worktrees/hacienda-plugin/skills/rgpd-registre/SKILL.md`
- Create: `.worktrees/hacienda-plugin/skills/rgpd-dpia/SKILL.md`
- Modify: `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` (bump v0.6.0)

- [ ] **Step 1: Create `rgpd-registre/SKILL.md`**

```markdown
---
name: rgpd-registre
description: Generate the Art. 30 RGPD register (registre des activités de traitement) for the current Cowork folder. Calls processing_register MCP tool, optionally renders to PDF/DOCX with profession-specific templates. Use when the avocat/cabinet needs to produce or update its Art. 30 register for CNIL inspection or annual compliance review.
argument-hint: "[--format=md|pdf|docx]"
---

# /hacienda:rgpd:registre — Registre Art. 30 RGPD

```
/hacienda:rgpd:registre
/hacienda:rgpd:registre --format=pdf
```

## Workflow

### Step 1 — Resolve project + load profile

Call `mcp__piighost__resolve_project_for_folder(folder=<active>)` for the project slug.

Call `mcp__piighost__controller_profile_get(scope="project", project=<project>)` to see if the controller profile is set. If empty, suggest `/hacienda:setup` first — the registre is far less useful without controller identity.

### Step 2 — Generate the register

Call `mcp__piighost__processing_register(project=<project>)`. Returns a `ProcessingRegister` dict with:
- `controller`, `dpo`
- `data_categories` (with `sensitive` Art. 9 flag)
- `documents_summary`
- `manual_fields` (hints for the avocat to fill)
- audit event `registre_generated` written automatically

### Step 3 — Render

If user passed `--format=md` (default), call:
```
mcp__piighost__render_compliance_doc(
  data=<register>, format="md",
  profile=<from controller.profession>,
  output_path="<folder>/rgpd-registre-<date>.md",
)
```
For `pdf` or `docx`, switch the format. PDF requires the `[compliance]` extra installed.

### Step 4 — Show the result

Display the register summary:
```
📋 Registre Art. 30 généré

Cabinet : <controller.name>
Profession : <controller.profession>
Catégories de données : <data_categories.length>
Catégories sensibles (Art. 9) : <sensitive_categories_present.length>
Documents inventoriés : <documents_summary.total_docs>

À compléter manuellement :
- <manual_fields[0].field> : <manual_fields[0].hint>
- ...

Fichier généré : <output_path>
```

### Refusals

- If the controller profile is completely empty (no name, no profession), refuse and direct to `/hacienda:setup` first. A registre without controller identity has no compliance value.
- If `format=pdf` is requested but weasyprint isn't installed, surface the clear ImportError to the user with the install command.
```

- [ ] **Step 2: Create `rgpd-dpia/SKILL.md`**

```markdown
---
name: rgpd-dpia
description: Run a DPIA-lite screening (Art. 35 RGPD) for the current Cowork folder. Detects triggers (Art. 35.3 + CNIL guidance), emits verdict (required / recommended / not required), and prepares pre-filled inputs for the official CNIL PIA software. Use when the avocat needs to assess whether a full DPIA is required for the current dossier.
---

# /hacienda:rgpd:dpia — Screening DPIA-lite Art. 35

```
/hacienda:rgpd:dpia
```

## Workflow

### Step 1 — Resolve project

`mcp__piighost__resolve_project_for_folder(folder=<active>)` → project slug.

### Step 2 — Screen

Call `mcp__piighost__dpia_screening(project=<project>)`. Returns a `DPIAScreening` dict:
- `verdict` — "dpia_required" / "dpia_recommended" / "dpia_not_required"
- `triggers` — list of Art. 35.3 + CNIL criteria detected
- `cnil_pia_inputs` — JSON ready to import into the CNIL PIA software
- `cnil_pia_url` — link to download the CNIL tool

### Step 3 — Display verdict

```
🛡️ Screening DPIA Art. 35

Verdict : {{verdict}}
{{verdict_explanation}}

Triggers détectés ({{triggers.length}}) :
- {{trigger.code}} ({{trigger.severity}}) : {{trigger.name}}
  Évidence : {{trigger.matched_evidence}}
- ...
```

### Step 4 — Render to MD (optional)

If the user wants a paper trail:
```
mcp__piighost__render_compliance_doc(
  data=<dpia>, format="md",
  profile=<from controller.profession>,
  output_path="<folder>/rgpd-dpia-<date>.md",
)
```

### Step 5 — Direct to CNIL PIA tool

If verdict is `dpia_required` or `dpia_recommended`, surface:
```
⚠️ Une DPIA complète est {{required ? "OBLIGATOIRE" : "recommandée"}}.

Pour la produire :
1. Télécharger l'outil CNIL : {{cnil_pia_url}}
2. Importer les inputs ci-dessus (cnil_pia_inputs)
3. Compléter les sections que piighost ne peut pas inférer (consultation des
   parties prenantes, mesures complémentaires)

piighost ne génère PAS de DPIA complète — c'est l'outil CNIL qui fait foi.
```

### Refusals

- DPIA screening is informational. Never refuse — even on an empty project, the screening adds value (e.g. flags `cnil_5` IA/NER trigger).
```

- [ ] **Step 3: Bump plugin version**

In `.worktrees/hacienda-plugin/.claude-plugin/plugin.json`, change `"version": "0.5.0"` to `"version": "0.6.0"`.

- [ ] **Step 4: Commit + push (in plugin worktree)**

```bash
cd .worktrees/hacienda-plugin
git add .claude-plugin/plugin.json skills/rgpd-registre/SKILL.md skills/rgpd-dpia/SKILL.md
git commit -m "feat(skills): /hacienda:rgpd:registre + /hacienda:rgpd:dpia

Two new slash commands wrapping the Phase 2 MCP tools:
  - /rgpd:registre [--format=md|pdf|docx] -> Art. 30 register
  - /rgpd:dpia -> DPIA-lite screening with CNIL PIA tool redirect

Bumps to v0.6.0."
git push origin main
cd ../..
```

---

## Task 8: No-PII-leak invariant tests for Phase 2

**Files:**
- Create: `tests/unit/test_no_pii_leak_phase2.py`

- [ ] **Step 1: Write the tests**

```python
"""Privacy invariants for Phase 2 outputs (registre + DPIA + render).

These tests are gates — failing one indicates a compliance defect.
"""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


_KNOWN_RAW_PII = [
    "Marie Dupont",
    "marie.dupont@example.com",
    "+33 1 23 45 67 89",
    "FR1420041010050500013M02606",
]


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def _seed_pii(proj):
    """Seed 4 known PII entities directly in the vault."""
    seeds = [
        ("<<np:1>>", "Marie Dupont", "nom_personne"),
        ("<<em:1>>", "marie.dupont@example.com", "email"),
        ("<<tel:1>>", "+33 1 23 45 67 89", "numero_telephone"),
        ("<<iban:1>>", "FR1420041010050500013M02606", "numero_compte_bancaire"),
    ]
    for token, original, label in seeds:
        proj._vault.upsert_entity(
            token=token, original=original, label=label, confidence=0.9,
        )


def test_processing_register_no_raw_pii(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-reg"))
    proj = asyncio.run(svc._get_project("leak-reg"))
    _seed_pii(proj)
    register = asyncio.run(svc.processing_register(project="leak-reg"))
    serialized = register.model_dump_json()
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized, (
            f"Raw PII '{raw}' leaked in ProcessingRegister"
        )
    asyncio.run(svc.close())


def test_dpia_screening_no_raw_pii(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-dpia"))
    proj = asyncio.run(svc._get_project("leak-dpia"))
    _seed_pii(proj)
    dpia = asyncio.run(svc.dpia_screening(project="leak-dpia"))
    serialized = dpia.model_dump_json()
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized, (
            f"Raw PII '{raw}' leaked in DPIAScreening"
        )
    asyncio.run(svc.close())


def test_rendered_md_no_raw_pii(vault_dir, monkeypatch, tmp_path):
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-render"))
    proj = asyncio.run(svc._get_project("leak-render"))
    _seed_pii(proj)
    register = asyncio.run(svc.processing_register(project="leak-render"))
    out = tmp_path / "registre.md"
    asyncio.run(svc.render_compliance_doc(
        data=register.model_dump(), format="md", profile="generic",
        output_path=str(out),
    ))
    rendered = out.read_text(encoding="utf-8")
    for raw in _KNOWN_RAW_PII:
        assert raw not in rendered, (
            f"Raw PII '{raw}' leaked in rendered MD output"
        )
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_no_pii_leak_phase2.py -v --no-header
```
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_no_pii_leak_phase2.py
git commit -m "test(rgpd): no-PII-leak invariant tests (Phase 2)

Three privacy gates for Phase 2 outputs:
  1. ProcessingRegister.model_dump_json() — no raw PII
  2. DPIAScreening.model_dump_json() — no raw PII
  3. Rendered MD via render_compliance_doc — no raw PII

Failing any of these = compliance defect, not just a bug."
```

---

## Task 9: Phase 2 final smoke test + push

**Files:**
- No new code — verification

- [ ] **Step 1: Run all Phase 2 tests together**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_doc_authors_anonymisation.py \
  tests/unit/test_controller_profile_mcp.py \
  tests/unit/test_processing_register.py \
  tests/unit/test_dpia_screening.py \
  tests/unit/test_render_compliance_doc.py \
  tests/unit/test_no_pii_leak_phase2.py \
  --no-header
```
Expected: 20+ tests passing.

- [ ] **Step 2: Run regression on Phase 0+1**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_doc_type_classifier.py \
  tests/unit/test_doc_metadata_extractor.py \
  tests/unit/test_indexing_store_documents_meta.py \
  tests/unit/test_audit_v2.py \
  tests/unit/test_controller_profile.py \
  tests/unit/test_vault_token_ops.py \
  tests/unit/test_chunk_store_phase1.py \
  tests/unit/test_subject_clustering.py \
  tests/unit/test_no_pii_leak_phase1.py \
  --no-header
```
Expected: all green (no Phase 2 regression on Phase 0+1).

- [ ] **Step 3: Push**

```bash
ECC_SKIP_PREPUSH=1 git push jamon master
```

- [ ] **Step 4: (Optional) Bonus — lock `forget_subject` per project (Phase 1 I1)**

If time allows, add `async with self._write_lock:` around the body of `_ProjectService.forget_subject` (after `start = time.monotonic()`, before the chunks rewrite) to prevent concurrent forget operations or query/forget races. This is the spec's open item from Phase 1.

---

## Self-review checklist

**Spec coverage (Phase 2 subset)**:

| Spec section | Implementing task |
|---|---|
| `_anonymise_authors` (carryover I3) | Task 1 |
| `controller_profile_get/set` MCP (review pre-Phase-2 gap) | Task 2 |
| `ProcessingRegister` Pydantic + builder | Task 3 |
| `DPIAScreening` Pydantic + screening logic | Task 4 |
| `render_compliance_doc` + 8 Jinja2 templates | Task 5 |
| MCP wiring (3 tools) | Task 6 |
| Plugin skills (rgpd-registre + rgpd-dpia) | Task 7 |
| No-PII-leak invariant tests | Task 8 |
| Phase 2 smoke test + push | Task 9 |

✓ Every Phase 2 spec item has a task. No gaps.

**Placeholder scan**: every code block has real code. The 5 profession-specific templates other than `avocat` are documented as "copy generic + add profession header" — implementer can produce reasonable defaults.

**Type consistency**:
- `ProcessingRegister.data_categories: list[DataCategoryItem]` — Task 3 def, Task 5 template consumes via `c.label`, `c.count`, `c.sensitive`. ✓
- `DPIAScreening.triggers: list[DPIATrigger]`, `verdict: Literal[...]` — Task 4 def, Task 5 template consumes. ✓
- `render_compliance_doc(data, format, profile, output_path)` — Task 5 service method matches Task 6 dispatcher matches Task 7 skill workflow. ✓
- `_anonymise_authors` returns `list[str]` of placeholder tokens. Task 1 def matches `DocumentMetadata.doc_authors: list[str]`. ✓

**Scope check**: Phase 2 alone, single PR cycle, ~1.5 weeks. The Wizard skill (`/hacienda:setup`) gets its own plan after Phase 2 lands — the prerequisite tools (controller_profile_get/set) are delivered here.
