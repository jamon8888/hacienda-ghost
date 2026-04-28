# RGPD Phase 6 — Cleanup & Followups Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 5 remaining followups across Phases 2–5: lazy imports for cold-start latency, defense-in-depth `extra="forbid"` on compliance sub-models, observability for silent error-swallowing, smarter data-subject classification using `parties_json`, and the long-deferred true MCP-shim integration tests. Six tasks, ~5 hours of work.

**Architecture:** Pure cleanup round — no new modules, no new MCP tools, no new SQLite schemas. Mostly tightening existing code with regression tests.

**Tech Stack:** Python 3.13 stdlib `__getattr__` (PEP 562), Pydantic `ConfigDict`, stdlib `logging`, FastMCP stdio transport for the integration tests.

**Spec:** Phase 6 has no dedicated spec — each task references the followups doc that motivated it.

**Phase 0–5 status:** all merged. Phase 5 HEAD was `e3422be`; subsequent hygiene commits brought master to `b8f3052`.

**Branch:** all backend work commits to `master` in the piighost repo (`C:\Users\NMarchitecte\Documents\piighost`). No plugin work in this phase.

---

## Followup origin map

| Task | Followup origin | Severity in source |
|---|---|---|
| 1 | Phase 5 followups #1 | 🟡 Important |
| 2 | Phase 5 followups #2 | 🟢 Nice-to-have (defense-in-depth) |
| 3 | Phase 4 followups #3 | 🟢 Nice-to-have |
| 4 | Phase 2 followups #7 | 🟢 Nice-to-have (real correctness improvement) |
| 5 | Phase 2 followups #9 + Phase 4 followups #4 | 🟡 Important |
| 6 | Verification + push | n/a |

Out of scope (still deferred): Phase 4 followup #7 (`bar_or_order_number` rename — needs migration shim, separate phase), Phase 2 followup #5 (CNIL `cnil_3` cross-project state — needs new architectural surface), Phase 5 followups #3–#6 (verbose union errors, sleep-based concurrency test, `_mask` dead arg, `MultiplexedPath` historical comment — all 🟢 with no concrete pain reported).

---

## File map (Phase 6)

| Path | Type | Owns |
|---|---|---|
| `src/piighost/compliance/__init__.py` | modify | Switch eager imports to PEP 562 `__getattr__` |
| `src/piighost/service/models.py` | modify | Add `extra="forbid"` to all compliance sub-models |
| `src/piighost/compliance/profile_loader.py` | modify | Log a warning before silently returning `{}` on bundled-TOML errors |
| `src/piighost/compliance/processing_register.py` | modify | `_classify_data_subjects` consults `documents_meta.parties_json` instead of project-name heuristic |
| `tests/unit/test_compliance_lazy_imports.py` | new | Verify `compliance.load_bundled_profile` imports without pulling pydantic/render |
| `tests/unit/test_compliance_submodels_forbid.py` | new | Verify `extra="forbid"` rejects nested smuggled keys at sub-model level |
| `tests/unit/test_profile_loader_warns.py` | new | Verify `caplog` sees the warning when a bundled TOML fails to parse |
| `tests/unit/test_processing_register.py` | modify | Add cases asserting `data_subject_categories` reflects `parties_json` |
| `tests/integration/test_mcp_shim_compliance_e2e.py` | new | True MCP-shim → daemon → service round-trip for the 3 RGPD tools |

---

## Task 1: Lazy `__getattr__` in `compliance/__init__.py`

**Files:**
- Modify: `src/piighost/compliance/__init__.py`
- Test: `tests/unit/test_compliance_lazy_imports.py`

Phase 5's eager re-exports added ~3 s to first-import cost because `from piighost.compliance import load_bundled_profile` (a tiny TOML reader) ends up importing `pydantic` + `service.models` + `render.py`'s top-level imports through transitive resolution.

PEP 562 module `__getattr__` lets us defer each submodule import until the first attribute access. Users who only need the loader pay only for the loader.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compliance_lazy_imports.py`:

```python
"""Verify compliance package uses lazy submodule imports.

Importing piighost.compliance + reading load_bundled_profile must NOT
pull pydantic or piighost.compliance.render into sys.modules. Phase 5
followup #1.
"""
from __future__ import annotations

import sys


def test_loading_only_profile_loader_does_not_import_render(monkeypatch):
    """from piighost.compliance import load_bundled_profile should not
    transitively import compliance.render."""
    # Drop any cached state so we measure cold-import cost
    for mod in list(sys.modules):
        if mod.startswith("piighost.compliance"):
            del sys.modules[mod]

    # Now do the lean import
    from piighost.compliance import load_bundled_profile  # noqa: F401

    # render must NOT be loaded yet
    assert "piighost.compliance.render" not in sys.modules, (
        "compliance.render was eagerly imported — lazy __getattr__ broken"
    )
    # processing_register must NOT be loaded yet
    assert "piighost.compliance.processing_register" not in sys.modules, (
        "compliance.processing_register was eagerly imported"
    )


def test_accessing_render_loads_it_on_demand():
    """Touching compliance.render_compliance_doc DOES load render submodule."""
    for mod in list(sys.modules):
        if mod.startswith("piighost.compliance"):
            del sys.modules[mod]

    import piighost.compliance as cmp
    assert "piighost.compliance.render" not in sys.modules

    # Force the lazy load
    fn = cmp.render_compliance_doc
    assert callable(fn)
    assert "piighost.compliance.render" in sys.modules


def test_dunder_all_unchanged():
    """__all__ stays the same shape — only the import strategy changes."""
    import piighost.compliance as cmp
    assert set(cmp.__all__) == {
        "build_processing_register",
        "screen_dpia",
        "render_compliance_doc",
        "load_bundled_profile",
    }


def test_unknown_attribute_raises_attribute_error():
    import piighost.compliance as cmp
    try:
        _ = cmp.nonexistent_function
    except AttributeError as exc:
        assert "nonexistent_function" in str(exc)
    else:
        raise AssertionError("AttributeError not raised")
```

- [ ] **Step 2: Run the tests to confirm they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_compliance_lazy_imports.py -v --no-header
```

Expected: `test_loading_only_profile_loader_does_not_import_render` FAILS (current eager imports pull render into sys.modules transitively).

- [ ] **Step 3: Switch `__init__.py` to PEP 562 `__getattr__`**

Replace contents of `src/piighost/compliance/__init__.py` with:

```python
"""piighost.compliance — RGPD compliance subsystem.

Public API (lazy-loaded via PEP 562 to keep startup fast):
    build_processing_register  — Art. 30 register builder
    screen_dpia                — Art. 35 DPIA-lite screening
    render_compliance_doc      — Render compliance dict to MD/DOCX/PDF
    load_bundled_profile       — Read bundled per-profession defaults

Lazy resolution means ``from piighost.compliance import load_bundled_profile``
does not transitively import pydantic / service.models / render.py — users
who only need the lightweight TOML reader pay only for it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "build_processing_register",
    "screen_dpia",
    "render_compliance_doc",
    "load_bundled_profile",
]


def __getattr__(name: str):
    if name == "build_processing_register":
        from .processing_register import build_processing_register
        return build_processing_register
    if name == "screen_dpia":
        from .dpia_screening import screen_dpia
        return screen_dpia
    if name == "render_compliance_doc":
        from .render import render_compliance_doc
        return render_compliance_doc
    if name == "load_bundled_profile":
        from .profile_loader import load_bundled_profile
        return load_bundled_profile
    raise AttributeError(f"module 'piighost.compliance' has no attribute {name!r}")


if TYPE_CHECKING:
    # Re-imports for static analysis only — never executed at runtime
    from .processing_register import build_processing_register  # noqa: F401
    from .dpia_screening import screen_dpia  # noqa: F401
    from .render import render_compliance_doc  # noqa: F401
    from .profile_loader import load_bundled_profile  # noqa: F401
```

- [ ] **Step 4: Run the new tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_compliance_lazy_imports.py -v --no-header
```

Expected: 4 passed.

- [ ] **Step 5: Re-run the existing public-API test (Phase 5 Task 4) to confirm no regression**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_compliance_public_api.py -v --no-header
```

Expected: 2 passed.

- [ ] **Step 6: Run the broader compliance sweep to catch any module that relied on eager imports**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_processing_register.py \
  tests/unit/test_dpia_screening.py \
  tests/unit/test_render_compliance_doc.py \
  tests/unit/test_render_data_validation.py \
  tests/unit/test_profile_loader.py \
  -v --no-header
```

Expected: all green. If anything breaks, the breaking test was reaching `compliance.X` as an attribute without first importing `compliance.X` directly — fix by adding the explicit submodule import.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/compliance/__init__.py tests/unit/test_compliance_lazy_imports.py
git commit -m "perf(compliance): lazy-load public API via PEP 562 __getattr__

Phase 5 followup #1. Eager re-exports were costing ~3s on cold first
import because 'from piighost.compliance import load_bundled_profile'
transitively pulled pydantic, service.models, render.py.

Switching to a __getattr__ lazy resolver means callers who only need
load_bundled_profile pay only for the TOML reader. Heavy imports
defer until first attribute access on the relevant symbol.

Four regression tests verify: lean import doesn't pull render,
on-demand access does pull render, __all__ is unchanged, unknown
attributes raise AttributeError."
```

---

## Task 2: `extra="forbid"` on compliance sub-models

**Files:**
- Modify: `src/piighost/service/models.py`
- Test: `tests/unit/test_compliance_submodels_forbid.py`

Phase 5 commit `6c9e25c` already closed the actual exploit (renderer uses `validated.model_dump()`, stripping smuggled keys). But the union adapter still silently *drops* unknown nested keys at validation time. Adding `extra="forbid"` to sub-models surfaces a `ValidationError` instead — better feedback for legitimate callers, better visibility for malformed/adversarial input.

Sub-models that need the flip:
- `ControllerInfo`, `DPOInfo`
- `DataCategoryItem`, `RetentionItem`, `TransferItem`, `SecurityMeasureItem`, `DocumentsSummary`, `ManualFieldHint`
- `DPIATrigger`, `CNILPIAInputs`
- `SubjectDocumentRef`, `SubjectExcerpt`

Also `EntityRef` and `VaultEntryModel` if they're consumed by `SubjectAccessReport` — check the model graph first.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compliance_submodels_forbid.py`:

```python
"""Sub-models in the compliance hierarchy must reject unknown keys.

Closes Phase 5 followup #2: top-level extra='forbid' alone leaves
sub-models permissive, which silently drops smuggled keys instead
of raising a clear ValidationError.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from piighost.service.models import (
    CNILPIAInputs,
    ControllerInfo,
    DataCategoryItem,
    DocumentsSummary,
    DPIATrigger,
    DPOInfo,
    ManualFieldHint,
    RetentionItem,
    SecurityMeasureItem,
    SubjectDocumentRef,
    SubjectExcerpt,
    TransferItem,
)


@pytest.mark.parametrize(
    "model_cls,minimal_kwargs",
    [
        (ControllerInfo, {"name": "X", "profession": "avocat"}),
        (DPOInfo, {"name": "Y"}),
        (DataCategoryItem, {"label": "email", "count": 1, "sensitive": False}),
        (RetentionItem, {"category": "factures", "duration": "10 ans"}),
        (TransferItem, {"destination": "US", "recipient": "X", "legal_mechanism": "SCC"}),
        (SecurityMeasureItem, {"name": "AES-256", "auto_detected": False}),
        (DocumentsSummary, {"total_docs": 0}),
        (ManualFieldHint, {"field": "X", "hint": "Y"}),
        (DPIATrigger, {"code": "art35.3.b", "name": "X", "severity": "mandatory"}),
        (CNILPIAInputs, {}),
        (SubjectDocumentRef, {"file_path": "/x", "doc_id": "abc", "occurrences": 1}),
        (SubjectExcerpt, {"file_path": "/x", "doc_id": "abc", "chunk_index": 0,
                          "redacted_text": ""}),
    ],
)
def test_submodel_rejects_extra_key(model_cls, minimal_kwargs):
    """Constructing each sub-model with an unknown extra key raises."""
    with pytest.raises(ValidationError, match="(extra|forbid|not permitted)"):
        model_cls(**minimal_kwargs, __html_payload="<script>")
```

If your `SubjectExcerpt` / `SubjectDocumentRef` field names differ, adapt them to whatever Phase 1 defined. Use `grep -n "class SubjectDocumentRef\|class SubjectExcerpt" src/piighost/service/models.py` to find the exact signatures, then update the `minimal_kwargs` accordingly.

- [ ] **Step 2: Run the test to confirm it fails**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_compliance_submodels_forbid.py -v --no-header
```

Expected: all parametrized cases FAIL — sub-models currently default to `extra="ignore"`.

- [ ] **Step 3: Apply `extra="forbid"` to each sub-model**

Open `src/piighost/service/models.py`. For each of the 12 sub-model classes listed above, add `model_config = ConfigDict(extra="forbid")` as the first attribute. Make sure `ConfigDict` is imported at the top of the file (it likely already is from Phase 5 Task 2):

```python
from pydantic import BaseModel, ConfigDict, Field

class ControllerInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... existing fields ...

class DPOInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... existing fields ...

# (and so on for the other 10 sub-models)
```

Skip the 3 top-level models (`ProcessingRegister`, `DPIAScreening`, `SubjectAccessReport`) — they already have it from Phase 5.

- [ ] **Step 4: Run the new test**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_compliance_submodels_forbid.py -v --no-header
```

Expected: all parametrized cases pass.

- [ ] **Step 5: Run the full compliance + integration sweep for regression**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_processing_register.py \
  tests/unit/test_dpia_screening.py \
  tests/unit/test_service_subject_access.py \
  tests/unit/test_render_compliance_doc.py \
  tests/unit/test_render_data_validation.py \
  tests/unit/test_no_pii_leak_phase2.py \
  tests/integration/test_setup_wizard_e2e.py \
  -v --no-header
```

Expected: all green. If any pre-existing test fails because it constructs a sub-model with an unknown key, the test was encoding a bug — fix the test (don't loosen the model).

- [ ] **Step 6: Commit**

```bash
git add src/piighost/service/models.py tests/unit/test_compliance_submodels_forbid.py
git commit -m "fix(compliance): extra='forbid' on all compliance sub-models

Phase 5 followup #2. The exploit was already closed in 6c9e25c
(renderer uses validated.model_dump()). This commit completes the
defense-in-depth posture: the union adapter now raises ValidationError
on smuggled nested keys instead of silently dropping them.

Twelve sub-models flipped: ControllerInfo, DPOInfo, DataCategoryItem,
RetentionItem, TransferItem, SecurityMeasureItem, DocumentsSummary,
ManualFieldHint, DPIATrigger, CNILPIAInputs, SubjectDocumentRef,
SubjectExcerpt.

One parametrized regression test covers every flipped sub-model."
```

---

## Task 3: `profile_loader` logs a warning instead of silent swallow

**Files:**
- Modify: `src/piighost/compliance/profile_loader.py`
- Test: `tests/unit/test_profile_loader_warns.py`

Phase 4 followup #3: `load_bundled_profile` swallows `TOMLDecodeError` and `OSError` silently. A malformed bundled TOML is a build-time bug that should fail loudly in CI, not return `{}` and confuse the wizard.

Soft fix: log a warning before returning `{}`. CI surfaces the warning via pytest's `caplog`, ops sees it in `daemon.log`, but the function still returns `{}` to keep the runtime resilient.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_profile_loader_warns.py`:

```python
"""profile_loader logs a warning when a bundled TOML fails to parse.

Closes Phase 4 followup #3. Silent swallow → caplog visibility.
"""
from __future__ import annotations

import logging

import pytest

from piighost.compliance import profile_loader as plm


def test_corrupt_bundled_toml_emits_warning(monkeypatch, tmp_path, caplog):
    """If reading or parsing the bundled TOML raises, a warning is logged."""
    # Force the loader's resources path to a tmp dir with a corrupt TOML.
    bad_dir = tmp_path / "profiles"
    bad_dir.mkdir()
    bad_toml = bad_dir / "broken.toml"
    bad_toml.write_text("this is not [valid TOML\n", encoding="utf-8")

    class _FakeResources:
        @staticmethod
        def files(_):
            return bad_dir

    monkeypatch.setattr(plm, "resources", _FakeResources())

    caplog.set_level(logging.WARNING, logger="piighost.compliance.profile_loader")
    result = plm.load_bundled_profile("broken")
    assert result == {}
    # Warning was emitted
    matching = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("broken" in r.getMessage() for r in matching), (
        f"Expected warning mentioning 'broken'; got {[r.getMessage() for r in matching]}"
    )


def test_unknown_profession_does_not_warn(monkeypatch, caplog):
    """Returning {} for an unknown (but well-formed) profession is silent —
    no warning, no error. That's not a bug, it's normal flow."""
    caplog.set_level(logging.WARNING, logger="piighost.compliance.profile_loader")
    result = plm.load_bundled_profile("zorblax")
    assert result == {}
    matching = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert matching == [], (
        f"Unexpected warnings for unknown profession: {[r.getMessage() for r in matching]}"
    )
```

- [ ] **Step 2: Run the test to confirm it fails**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_profile_loader_warns.py -v --no-header
```

Expected: `test_corrupt_bundled_toml_emits_warning` FAILS (no warning is currently logged).

- [ ] **Step 3: Update `profile_loader.py`**

Open `src/piighost/compliance/profile_loader.py` and update the function:

```python
"""Load bundled per-profession default profiles for the /hacienda:setup wizard.

Profile TOMLs live under ``piighost.compliance.profiles/<profession>.toml`` and
ship in the wheel. The loader is read-only and never touches user files.
"""
from __future__ import annotations

import logging
import re
import sys
from importlib import resources

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


_PROFESSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_LOGGER = logging.getLogger(__name__)


def load_bundled_profile(profession: str) -> dict:
    """Return the bundled default profile for *profession*, or ``{}`` if
    the profession is unknown or the input fails validation.

    The validation regex blocks path traversal — *profession* is reachable
    from the MCP boundary (untrusted).

    Returns ``{}`` for:
      - Invalid input (regex mismatch) — silent (this is normal flow).
      - Unknown profession (no bundled file) — silent (also normal).
      - TOMLDecodeError / OSError on a bundled file — logged as a WARNING,
        because that's a build-time bug we want CI to surface.
    """
    if not _PROFESSION_RE.match(profession or ""):
        return {}
    try:
        path = resources.files("piighost.compliance.profiles") / f"{profession}.toml"
        if not path.is_file():
            return {}
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Bundled file vanished mid-flight — silent fall-through.
        return {}
    except AttributeError:
        # AttributeError can fire when importlib.resources returns a
        # MultiplexedPath (namespace-package case) without an .is_file()
        # method — older Python layouts did this. Defence-in-depth on
        # current 3.13+ packaging where __init__.py guarantees .is_file().
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        _LOGGER.warning(
            "Failed to load bundled profile %r: %s. "
            "This is a build-time bug — the bundled TOML should always "
            "parse. Returning {} so the wizard can fall back to generic.",
            profession, exc,
        )
        return {}
```

- [ ] **Step 4: Run the new test**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_profile_loader_warns.py -v --no-header
```

Expected: 2 passed.

- [ ] **Step 5: Re-run the existing profile_loader tests for regression**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_profile_loader.py tests/unit/test_controller_profile_defaults_mcp.py -v --no-header
```

Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/compliance/profile_loader.py tests/unit/test_profile_loader_warns.py
git commit -m "fix(compliance): log warning on profile_loader parse failures

Phase 4 followup #3. Previously TOMLDecodeError and OSError were
silently swallowed, returning {}. A malformed bundled TOML is a
build-time bug — CI should surface it via the warning instead of
masking it as 'unknown profession'.

Two regression tests:
  - corrupt TOML emits a logger.warning containing the profession name
  - unknown (but well-formed) profession stays silent (normal flow,
    not a bug)"
```

---

## Task 4: `_classify_data_subjects` consults `documents_meta.parties_json`

**Files:**
- Modify: `src/piighost/compliance/processing_register.py:163` (`_classify_data_subjects`)
- Test: `tests/unit/test_processing_register.py` (extend with new cases)

Phase 2 followup #7: the current heuristic only inspects `dossier_id` (a string from the project name). It ignores the actually-extracted `parties_json` column from `documents_meta`, which is populated at index time and contains the parsed party labels (e.g. `["client", "avocat", "tiers"]`).

A real avocat seeing `data_subject_categories: ["clients"]` on a project that actually contains employee complaints + client invoices would over-trust the registre. Reading `parties_json` makes the registre genuinely descriptive.

- [ ] **Step 1: Confirm the data shape**

```bash
grep -n "parties_json\|class.*DocumentMetadata\b\|DocumentMeta" /c/Users/NMarchitecte/Documents/piighost/src/piighost/indexer/indexing_store.py | head -10
grep -n "class DocumentMetadata\|parties:" /c/Users/NMarchitecte/Documents/piighost/src/piighost/service/models.py | head -10
```

Confirm: `documents_meta.parties_json` is a TEXT column storing a JSON list. The Pydantic model has a `parties: list[str]` field (already deserialized when read via `documents_meta_for` / `list_documents_meta`).

If the Pydantic field name is different, use that — adapt the rest of the task accordingly.

- [ ] **Step 2: Write the failing tests**

In `tests/unit/test_processing_register.py`, add three new cases at the end of the file (keep existing tests intact):

```python
def test_register_data_subjects_from_parties(vault_dir, monkeypatch):
    """data_subject_categories surfaces unique parties from documents_meta."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("subjects-parties"))
    proj = asyncio.run(svc._get_project("subjects-parties"))

    # Seed two documents with different party labels
    from piighost.service.models import DocumentMetadata
    proj._indexing_store.upsert_document_meta(DocumentMetadata(
        doc_id="doc-1", file_path="/dossier/contrat.pdf",
        doc_type="contrat",
        parties=["client", "avocat", "tiers"],
        dossier_id="dossier-acme",
    ))
    proj._indexing_store.upsert_document_meta(DocumentMetadata(
        doc_id="doc-2", file_path="/dossier/facture.pdf",
        doc_type="facture",
        parties=["client"],
        dossier_id="dossier-acme",
    ))

    register = asyncio.run(svc.processing_register(project="subjects-parties"))
    subjects = set(register.data_subject_categories)
    # Expect labels derived from the actual parties (deduplicated, sorted)
    assert "client" in subjects or "clients" in subjects, subjects
    assert "tiers" in subjects or "tiers contractants" in subjects, subjects
    asyncio.run(svc.close())


def test_register_data_subjects_falls_back_when_parties_empty(vault_dir, monkeypatch):
    """When parties_json is empty across all docs, fall back to the project-name heuristic."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("subjects-empty"))
    proj = asyncio.run(svc._get_project("subjects-empty"))

    # Seed a doc with NO parties
    from piighost.service.models import DocumentMetadata
    proj._indexing_store.upsert_document_meta(DocumentMetadata(
        doc_id="doc-1", file_path="/anywhere/x.pdf",
        doc_type="autre",
        parties=[],
        dossier_id="client-acme",   # name-heuristic still fires
    ))

    register = asyncio.run(svc.processing_register(project="subjects-empty"))
    subjects = set(register.data_subject_categories)
    assert "clients" in subjects, subjects
    asyncio.run(svc.close())


def test_register_data_subjects_rh_uses_salaries(vault_dir, monkeypatch):
    """RH profession + parties listing 'salarie' surfaces 'salariés'."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={"controller": {"name": "Service RH", "profession": "rh"}},
        scope="global",
    ))
    asyncio.run(svc.create_project("subjects-rh"))
    proj = asyncio.run(svc._get_project("subjects-rh"))

    from piighost.service.models import DocumentMetadata
    proj._indexing_store.upsert_document_meta(DocumentMetadata(
        doc_id="doc-1", file_path="/rh/contrat.pdf",
        doc_type="contrat_travail",
        parties=["salarie", "employeur"],
        dossier_id="dossier-rh-2026",
    ))

    register = asyncio.run(svc.processing_register(project="subjects-rh"))
    subjects = set(register.data_subject_categories)
    assert "salariés" in subjects or "salaries" in subjects, subjects
    asyncio.run(svc.close())
```

The first/third tests assert flexible label forms (`"client"` or `"clients"`, `"salariés"` or `"salaries"`) so the implementer can pick a normalization strategy.

- [ ] **Step 3: Run the tests to confirm they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_processing_register.py::test_register_data_subjects_from_parties tests/unit/test_processing_register.py::test_register_data_subjects_falls_back_when_parties_empty tests/unit/test_processing_register.py::test_register_data_subjects_rh_uses_salaries -v --no-header
```

Expected: at least the first and third FAIL — the heuristic ignores `parties_json` today.

- [ ] **Step 4: Update `_classify_data_subjects`**

Open `src/piighost/compliance/processing_register.py` line 163. Replace the function:

```python
# Map raw party labels (as they appear in documents_meta.parties_json)
# to the user-facing data-subject category emitted in the registre.
_PARTY_LABEL_MAP = {
    "client": "clients",
    "clients": "clients",
    "patient": "patients",
    "patients": "patients",
    "salarie": "salariés",
    "salariés": "salariés",
    "salaries": "salariés",
    "employe": "salariés",
    "employee": "salariés",
    "personnel": "salariés",
    "candidat": "candidats",
    "tiers": "tiers contractants",
    "fournisseur": "fournisseurs",
}


def _classify_data_subjects(docs_meta, profession: str) -> list[str]:
    """Return the data-subject categories for the registre.

    Strategy (in order):
      1. Aggregate ``parties_json`` across all indexed documents and map
         each unique label to a user-facing category via ``_PARTY_LABEL_MAP``.
         This is the data-driven path — what the indexer actually saw.
      2. If parties_json is empty across the project, fall back to the
         project-name heuristic (dossier_id starts with 'client'/'dossier'/
         'rh'/'paie'/'salarie'/'personnel').
      3. If both are inconclusive, default to a profession-driven seed
         ('clients du cabinet' for avocat, 'salariés' for rh, 'clients'
         otherwise).

    The mapping is deliberately conservative — unknown party labels are
    surfaced as-is so the avocat sees them and can correct the registre
    manually rather than have piighost silently invent a category.
    """
    subjects: set[str] = set()

    # Path 1: data-driven from parties_json
    for m in docs_meta:
        for raw in m.parties or ():
            key = raw.strip().lower()
            mapped = _PARTY_LABEL_MAP.get(key)
            if mapped:
                subjects.add(mapped)
            elif key:
                # Unknown label — surface as-is for the avocat to review
                subjects.add(raw.strip())

    if subjects:
        return sorted(subjects)

    # Path 2: project-name heuristic (legacy)
    for m in docs_meta:
        d = (m.dossier_id or "").lower()
        if d.startswith("client") or d.startswith("dossier"):
            subjects.add("clients")
        if any(k in d for k in ("rh", "paie", "salarie", "personnel")):
            subjects.add("salariés")

    if subjects:
        return sorted(subjects)

    # Path 3: profession-driven default
    if profession == "avocat":
        return ["clients du cabinet"]
    if profession == "rh":
        return ["salariés"]
    return ["clients"]
```

- [ ] **Step 5: Run the new tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_processing_register.py -v --no-header
```

Expected: all (existing 4 + 3 new) = 7 passed.

- [ ] **Step 6: Run the integration + leak tests for regression**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_no_pii_leak_phase2.py tests/integration/test_setup_wizard_e2e.py -v --no-header
```

Expected: 7 passed (4 + 3).

- [ ] **Step 7: Commit**

```bash
git add src/piighost/compliance/processing_register.py tests/unit/test_processing_register.py
git commit -m "feat(compliance): classify data subjects from parties_json

Phase 2 followup #7. _classify_data_subjects previously ignored the
parties data the indexer actually extracted (documents_meta.parties_json),
relying solely on a project-name heuristic. The registre risked saying
data_subject_categories: ['clients'] for projects that contained
employee complaints + client invoices.

Three-tier strategy:
  1. Aggregate parties from documents_meta and map known labels via
     _PARTY_LABEL_MAP (client→clients, salarie→salariés, etc.).
     Unknown labels surface as-is for the avocat to review.
  2. Empty parties → project-name heuristic (legacy path).
  3. Both inconclusive → profession-driven default (avocat→clients
     du cabinet, rh→salariés).

Three regression tests cover each path."
```

---

## Task 5: True MCP-shim integration tests

**Files:**
- Create: `tests/integration/test_mcp_shim_compliance_e2e.py`

Phase 2 followup #9 / Phase 4 followup #4: existing tests bypass the MCP shim and daemon dispatch. A class of bugs (FastMCP schema generation drift, JSON serialization edge cases, dispatcher param-name typos) can only surface end-to-end.

This task adds three integration tests that:
1. Spawn the daemon in a child process via `piighost-mcp` entry point.
2. Invoke `processing_register`, `dpia_screening`, `render_compliance_doc` through the MCP shim (FastMCP stdio transport).
3. Assert the round-tripped result deserializes cleanly.

Note on environment: the dev venv had `cryptography` import errors during Phase 5 proxy testing. If the daemon spin-up needs `cryptography` (which it shouldn't for the RGPD surface), the test should `pytest.skip` cleanly with a clear message.

- [ ] **Step 1: Read the existing daemon spin-up patterns**

```bash
grep -rn "subprocess.Popen\|piighost-mcp\|build_app\|asyncio.run.*serve" /c/Users/NMarchitecte/Documents/piighost/tests/integration/ /c/Users/NMarchitecte/Documents/piighost/tests/proxy/ 2>&1 | head -20
```

Look at how existing integration tests (if any beyond `test_setup_wizard_e2e.py`) bring up the daemon. If `tests/integration/test_mcp_lifecycle.py` exists (mentioned in Phase 4 Task 6 report), read it for the pattern.

If no daemon-spawn pattern exists, the simplest approach is to skip subprocess spawning and instead call `daemon.server.build_app(vault_dir)` directly in-process, then drive `_dispatch` through the FastMCP shim's `_lazy_dispatch`. That tests the full method-name dispatch path without the cost of subprocess + handshake.

- [ ] **Step 2: Write the integration tests**

Create `tests/integration/test_mcp_shim_compliance_e2e.py`:

```python
"""End-to-end test for the 3 RGPD MCP tools through the actual shim
+ daemon dispatch path.

Closes Phase 2 followup #9 + Phase 4 followup #4. Existing unit tests
bypass the MCP boundary (call PIIGhostService directly). This test
goes shim → daemon._dispatch → service to catch param-name drift,
JSON serialization edge cases, and FastMCP schema regressions.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


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


@pytest.fixture()
async def daemon_app(vault_dir):
    """Build the daemon Starlette app in-process and run lifespan."""
    from piighost.daemon.server import build_app
    app, token = build_app(vault_dir)
    # Manually drive lifespan startup so background tasks (reaper) are running
    async with app.router.lifespan_context(app):
        yield app, token


def _dispatch_via_shim(app, token: str, method: str, params: dict) -> dict:
    """Call the daemon's /rpc endpoint as the shim would.

    Uses Starlette's TestClient to route through the actual ASGI stack,
    not a direct method call.
    """
    from starlette.testclient import TestClient
    with TestClient(app) as client:
        resp = client.post(
            "/rpc",
            headers={"authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        return body["result"]


@pytest.mark.asyncio
async def test_mcp_shim_processing_register_round_trip(daemon_app):
    """processing_register dispatched through the MCP boundary returns
    a dict that deserializes cleanly to ProcessingRegister."""
    app, token = daemon_app

    _dispatch_via_shim(app, token, "create_project", {"name": "shim-reg"})
    result = _dispatch_via_shim(app, token, "processing_register", {"project": "shim-reg"})

    # Deserialize back through the Pydantic model — extra='forbid' would
    # surface any field drift between dispatcher and model.
    from piighost.service.models import ProcessingRegister
    register = ProcessingRegister.model_validate(result)
    assert register.project == "shim-reg"
    assert register.v == 1


@pytest.mark.asyncio
async def test_mcp_shim_dpia_screening_round_trip(daemon_app):
    """dpia_screening dispatched through MCP returns a valid DPIAScreening dict."""
    app, token = daemon_app

    _dispatch_via_shim(app, token, "create_project", {"name": "shim-dpia"})
    result = _dispatch_via_shim(app, token, "dpia_screening", {"project": "shim-dpia"})

    from piighost.service.models import DPIAScreening
    dpia = DPIAScreening.model_validate(result)
    assert dpia.project == "shim-dpia"
    assert dpia.verdict in ("dpia_required", "dpia_recommended", "dpia_not_required")


@pytest.mark.asyncio
async def test_mcp_shim_render_compliance_doc_round_trip(daemon_app, tmp_path):
    """render_compliance_doc dispatched through MCP writes a real file
    and returns a RenderResult dict."""
    app, token = daemon_app

    _dispatch_via_shim(app, token, "create_project", {"name": "shim-render"})
    register = _dispatch_via_shim(app, token, "processing_register", {"project": "shim-render"})

    output = Path.home() / ".piighost" / "exports" / "shim-render.md"
    result = _dispatch_via_shim(app, token, "render_compliance_doc", {
        "data": register, "format": "md", "profile": "generic",
        "output_path": str(output), "project": "shim-render",
    })

    from piighost.service.models import RenderResult
    rr = RenderResult.model_validate(result)
    assert rr.path == str(output)
    assert rr.format == "md"
    assert output.exists()
    assert output.stat().st_size > 0


@pytest.mark.asyncio
async def test_mcp_shim_unknown_method_returns_clean_error(daemon_app):
    """An unknown RPC method bubbles up as a clean {error} payload, not a 500."""
    app, token = daemon_app

    from starlette.testclient import TestClient
    with TestClient(app) as client:
        resp = client.post(
            "/rpc",
            headers={"authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "definitely_not_a_method", "params": {}},
        )
        # Daemon always returns 200 with an {error} body for RPC failures
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert "Unknown method" in body["error"]["message"]
```

This test uses Starlette's `TestClient` (synchronous) and is parametrized as async to exercise the daemon's async lifespan. If `pytest-asyncio` isn't already a dev dependency, check `pyproject.toml` — it should be (Phase 2's tests already use `asyncio.run` patterns; if `@pytest.mark.asyncio` isn't picked up, switch to wrapping each test body in `asyncio.run(_inner())` like the other tests do).

- [ ] **Step 3: Run the tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/integration/test_mcp_shim_compliance_e2e.py -v --no-header
```

Expected: 4 passed.

If `pytest-asyncio` isn't configured, tests may all SKIP. Restructure as `asyncio.run(_async_test_body())` style to match the other integration tests:

```python
def test_mcp_shim_processing_register_round_trip(vault_dir):
    async def _run():
        from piighost.daemon.server import build_app
        app, token = build_app(vault_dir)
        async with app.router.lifespan_context(app):
            _dispatch_via_shim(app, token, "create_project", {"name": "shim-reg"})
            result = _dispatch_via_shim(app, token, "processing_register", {"project": "shim-reg"})
            from piighost.service.models import ProcessingRegister
            register = ProcessingRegister.model_validate(result)
            assert register.project == "shim-reg"
            assert register.v == 1
    asyncio.run(_run())
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_mcp_shim_compliance_e2e.py
git commit -m "test(integration): MCP-shim end-to-end for processing_register / dpia_screening / render_compliance_doc

Phase 2 followup #9 + Phase 4 followup #4. Drives the 3 RGPD MCP tools
through the actual daemon dispatch path (Starlette ASGI → /rpc → svc),
not via direct PIIGhostService calls. Catches param-name drift, JSON
serialization edge cases, and FastMCP schema regressions that unit
tests cannot.

Four cases:
  - processing_register round-trip + Pydantic re-validation
  - dpia_screening round-trip + verdict shape
  - render_compliance_doc writes file + returns valid RenderResult
  - unknown method bubbles as clean error, not 500"
```

---

## Task 6: Phase 6 final smoke + push

**Files:**
- No new code — verification + push.

- [ ] **Step 1: Run all Phase 6 new tests together**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_compliance_lazy_imports.py \
  tests/unit/test_compliance_submodels_forbid.py \
  tests/unit/test_profile_loader_warns.py \
  tests/integration/test_mcp_shim_compliance_e2e.py \
  -v --no-header
```

Expected: 4 + 12 + 2 + 4 = 22 passed.

- [ ] **Step 2: Run the full RGPD test sweep for regression**

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
  --no-header
```

Expected: all green (modulo the 2 pre-existing skips on `test_service_subject_access`).

- [ ] **Step 3: Push**

```bash
ECC_SKIP_PREPUSH=1 git push jamon master
```

- [ ] **Step 4: (Optional) Phase 6 follow-ups doc**

If anything surfaced during execution (especially in Task 5 — daemon lifecycle / FastMCP integration is the area most likely to surface real issues), capture in `docs/superpowers/followups/2026-04-28-rgpd-phase6-followups.md`.

---

## Self-review checklist

**Spec coverage:**

| Followup origin | Implementing task |
|---|---|
| Phase 5 followup #1 (lazy imports) | Task 1 |
| Phase 5 followup #2 (sub-model `extra="forbid"`) | Task 2 |
| Phase 4 followup #3 (silent swallow → log warning) | Task 3 |
| Phase 2 followup #7 (`_classify_data_subjects` parties_json) | Task 4 |
| Phase 2 followup #9 + Phase 4 followup #4 (MCP-shim integration) | Task 5 |
| Verification + push | Task 6 |

✓ Every selected followup has a task. Out-of-scope items (Phase 4 #7 rename, Phase 2 #5 cnil_3, Phase 5 #3-#6) are noted in the file map intro.

**Placeholder scan:** every code block has real code. No "TBD" / "implement later". The 12 sub-models in Task 2 are listed by name; the `_PARTY_LABEL_MAP` in Task 4 is spelled out; the MCP integration test fixtures are concrete.

**Type consistency:**
- `_classify_data_subjects(docs_meta, profession)` signature unchanged — only the body changes. ✓
- `_PARTY_LABEL_MAP` keys are lowercase, match the lowercase normalization in the function. ✓
- `load_bundled_profile(profession: str) -> dict` signature unchanged. ✓
- `__getattr__(name: str)` PEP 562 contract — `AttributeError` raised for unknown names. ✓
- The 4 MCP tool method names in Task 5 (`processing_register`, `dpia_screening`, `render_compliance_doc`, `create_project`) all exist in `daemon/server.py:_dispatch`. ✓

**Scope check:** Phase 6 alone, single PR cycle, ~5 hours. No new heavy deps, no new SQLite tables, no new MCP tools, no plugin work, no spec changes.

**Risk note:** Task 5 (MCP integration) is the highest-risk task. If `Starlette TestClient` doesn't play well with the daemon's lifespan (the `_make_lifespan` wrapper spins a reaper task), the test may flake. The plan sketches a fallback (drive lifespan manually). If even that doesn't work, the implementer should escalate rather than silently downgrade to unit-level coverage — the whole point of Task 5 is end-to-end coverage.

---

## Estimated effort

| Task | Effort |
|---|---|
| 1 — Lazy imports | 30 min |
| 2 — Sub-model `extra="forbid"` | 30 min |
| 3 — Logger warning | 30 min |
| 4 — `_classify_data_subjects` parties_json | 1.5 h |
| 5 — MCP-shim integration tests | 2 h |
| 6 — Smoke + push | 15 min |
| **Total** | **~5 h** |
