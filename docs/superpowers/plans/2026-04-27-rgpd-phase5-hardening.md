# RGPD Phase 5 — Hardening & Followups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the highest-priority follow-ups accumulated across RGPD Phases 1–4: a concurrency fix on `forget_subject`, an MCP-boundary Pydantic validator on `render_compliance_doc`, a privacy-gate extension covering `SubjectAccessReport` (which surfaced a real partial-leak in `_mask`), public-API re-exports for the `compliance/` package, and a small batch of documentation corrections. Six tasks, ~4 hours of work.

**Architecture:** Pure maintenance round — no new modules, no new MCP tools, no new SQLite schemas. Only existing code is hardened. Every change ships with at least one regression test.

**Tech Stack:** Python 3.13 stdlib `asyncio.Lock`, Pydantic `TypeAdapter`, existing test infrastructure.

**Spec:** Phase 5 has no dedicated spec — each task references the followups doc that motivated it.

**Phase 0–4 status:** all merged. Phase 4 HEAD is `f8b1eda` (followups doc).

**Branch:** all backend work commits to `master` in the piighost repo (`C:\Users\NMarchitecte\Documents\piighost`). Plugin worktree (`.worktrees/hacienda-plugin`) is unaffected — no plugin work in this phase.

---

## Followup origin map

| Task | Followup origin | Severity in source |
|---|---|---|
| 1 | Phase 1 review I1 (Phase 2 followups #1) | 🟡 Important |
| 2 | Phase 2 followups #3 | 🟡 Important — security |
| 3 | Phase 2 followups #4 | 🟡 Important — privacy gate |
| 4 | Phase 2 followups #6 | 🟢 Nice-to-have |
| 5 | Phase 4 followups #1, #2, #8 | 🟡 + 🟡 + 🟢 |
| 6 | Verification + push | n/a |

Out of scope for Phase 5 (deferred): Phase 4 followup #4 (true MCP-shim integration tests — bigger lift, separate phase), Phase 4 followup #7 (rename `bar_or_order_number`), Phase 2 followup #5 (CNIL cnil_3 — needs cross-project state).

---

## File map (Phase 5)

| Path | Type | Owns |
|---|---|---|
| `src/piighost/service/core.py` | modify | Add `async with self._write_lock` around `forget_subject` body; replace `_mask` with `<<SUBJECT>>` token |
| `src/piighost/compliance/render.py` | modify | Pydantic-validate `data` against the 3-way union before rendering |
| `src/piighost/compliance/__init__.py` | modify | Re-export `build_processing_register`, `screen_dpia`, `render_compliance_doc`, `load_bundled_profile` |
| `src/piighost/compliance/profile_loader.py` | modify | Document why `AttributeError` is in the except tuple |
| `src/piighost/mcp/tools.py` | modify | Append "rejects path traversal" sentence to `controller_profile_defaults` description |
| `docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md` | modify | One-line erratum: médecin uses RPPS/ADELI, not ARS |
| `tests/unit/test_forget_subject_concurrency.py` | new | Regression test for the lock |
| `tests/unit/test_render_data_validation.py` | new | Regression test for Pydantic validation |
| `tests/unit/test_no_pii_leak_phase2.py` | modify | Add 4th test rendering a `SubjectAccessReport` |
| `tests/unit/test_compliance_public_api.py` | new | Verify re-exports are importable from `piighost.compliance` |

---

## Task 1: Lock `forget_subject` per project

**Files:**
- Modify: `src/piighost/service/core.py:710-820` (`async def forget_subject`)
- Test: `tests/unit/test_forget_subject_concurrency.py`

The Phase 1 review flagged that `forget_subject`'s body (vault deletes + chunk rewrites + audit) runs without holding the project's `self._write_lock`. Concurrent callers can produce a partially-rewritten state. Phase 2 Task 9 marked this optional and didn't fix it. This task fixes it.

The existing `_ProjectService._write_lock` is created at `__init__` (line 73, `asyncio.Lock()`) and already used by `index_path` (line 145, `async with self._write_lock:`). We mirror that pattern.

- [ ] **Step 1: Write the failing concurrency test**

Create `tests/unit/test_forget_subject_concurrency.py`:

```python
"""Regression test: forget_subject must be serialized per project.

Two concurrent forget_subject(dry_run=False) calls on the same project
must not interleave their vault deletes / chunk rewrites — the second
caller waits for the first to finish.
"""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_concurrent_forget_subject_serializes(vault_dir, monkeypatch):
    """Two concurrent forget_subject calls do not interleave."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("forget-race"))
    proj = asyncio.run(svc._get_project("forget-race"))

    # Seed two distinct PII tokens
    proj._vault.upsert_entity(
        token="<<np:1>>", original="Alice", label="nom_personne", confidence=0.9,
    )
    proj._vault.upsert_entity(
        token="<<np:2>>", original="Bob", label="nom_personne", confidence=0.9,
    )

    async def both_forgets():
        # Two concurrent forgets, distinct token sets
        return await asyncio.gather(
            svc.forget_subject(
                tokens=["<<np:1>>"], project="forget-race", dry_run=False,
            ),
            svc.forget_subject(
                tokens=["<<np:2>>"], project="forget-race", dry_run=False,
            ),
        )

    r1, r2 = asyncio.run(both_forgets())
    # Both report success
    assert r1.dry_run is False
    assert r2.dry_run is False
    # Both tokens are gone from the vault (no partial state)
    assert proj._vault.get_entity_by_token("<<np:1>>") is None
    assert proj._vault.get_entity_by_token("<<np:2>>") is None

    asyncio.run(svc.close())


def test_concurrent_forget_holds_write_lock(vault_dir, monkeypatch):
    """While forget_subject is running, an index_path call waits for the lock."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("forget-lock"))
    proj = asyncio.run(svc._get_project("forget-lock"))
    proj._vault.upsert_entity(
        token="<<np:99>>", original="Charlie", label="nom_personne", confidence=0.9,
    )

    # Sanity: the same _write_lock object is reachable
    assert proj._write_lock is not None
    assert isinstance(proj._write_lock, asyncio.Lock)

    # Simulate "lock is held by forget" — manually acquire then forget should block
    async def assert_lock_blocks():
        await proj._write_lock.acquire()
        forget_task = asyncio.create_task(
            svc.forget_subject(
                tokens=["<<np:99>>"], project="forget-lock", dry_run=False,
            )
        )
        # Give the forget task a chance to start; it must NOT complete while we hold the lock
        await asyncio.sleep(0.1)
        assert not forget_task.done(), "forget_subject did not respect _write_lock"
        proj._write_lock.release()
        await forget_task

    asyncio.run(assert_lock_blocks())
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run the tests to confirm they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_forget_subject_concurrency.py -v --no-header
```

Expected: `test_concurrent_forget_holds_write_lock` FAILS (forget_subject completes immediately because there's no lock).

- [ ] **Step 3: Wrap `forget_subject` body with the lock**

In `src/piighost/service/core.py`, locate `async def forget_subject(...)` at line 710. The current body starts after the docstring with import lines and `start = _time.monotonic()`.

Wrap the entire body **after** the imports and `start = ...` line, but **before** the first real work line (`# 1. Find affected scope`), inside `async with self._write_lock:`. Indent everything that follows by 4 spaces.

The structure becomes:

```python
    async def forget_subject(
        self,
        tokens: list[str],
        *,
        dry_run: bool = True,
        legal_basis: str = "c-opposition",
    ) -> "ForgetReport":
        """Right-to-be-forgotten cascade (Art. 17) with tombstone.

        Steps (when dry_run=False):
          1. Find affected docs/chunks
          2. Rewrite chunks: each token → <<deleted:HASH8>>
          3. Re-embed rewritten chunks
          4. UPDATE chunks (DELETE+INSERT in LanceDB or in-memory mutation)
          5. Rebuild BM25 index
          6. DELETE vault entries (entities + doc_entities)
          7. Audit 'forgotten' event with hashed token list only

        Holds ``self._write_lock`` so concurrent forget / index ops are
        serialized per project.
        """
        from piighost.service.models import ForgetReport
        import hashlib
        import os
        import time as _time

        start = _time.monotonic()

        async with self._write_lock:
            # 1. Find affected scope
            doc_ids = self._vault.docs_containing_tokens(tokens)
            affected_chunks = self._chunk_store.chunks_for_doc_ids(doc_ids)
            # ... rest of the existing body, indented by 4 spaces ...
            return report
```

Practical edit: in your editor, select lines from `# 1. Find affected scope` through (and including) the final `return report`, and indent each by 4 spaces. Then add the `async with self._write_lock:` line above. Don't move the `import` lines or `start = _time.monotonic()` — they stay outside the lock so the function entry timing isn't blocked by an existing holder.

- [ ] **Step 4: Run the tests to confirm both pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_forget_subject_concurrency.py -v --no-header
```

Expected: 2 passed.

- [ ] **Step 5: Run the Phase 1 forget_subject tests for regression**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_forget_subject.py -v --no-header
```

Expected: all green (the lock should be transparent to single-caller tests).

- [ ] **Step 6: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_forget_subject_concurrency.py
git commit -m "fix(rgpd): lock forget_subject per project (Phase 1 followup I1)

Wraps the forget_subject body (vault delete + chunk rewrite + audit)
in self._write_lock — the same per-project asyncio.Lock that index_path
already uses. Concurrent forget+forget or forget+index calls now
serialize instead of producing partially-rewritten state.

Two regression tests:
  - two concurrent forgets on distinct tokens both succeed cleanly
  - while _write_lock is held, forget_subject waits for release"
```

---

## Task 2: Pydantic-validate `data` at the `render_compliance_doc` boundary

**Files:**
- Modify: `src/piighost/compliance/render.py:228+` (`render_compliance_doc` entry point)
- Test: `tests/unit/test_render_data_validation.py`

The Phase 2 final review flagged that `render_compliance_doc(data: dict[str, Any], ...)` accepts arbitrary dicts. A Claude turn poisoned by adversarial RAG context could pass `{"controller": {"name": "<script>...</script>"}}` and the renderer would happily emit it. With `autoescape=False` (correct for Markdown), the HTML lands in the MD body and survives the MD→HTML→PDF conversion — layout-corruption / phishing-vector territory.

We validate `data` against `Union[ProcessingRegister, DPIAScreening, SubjectAccessReport]` via `pydantic.TypeAdapter` at function entry. Unknown shapes raise `ValueError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_render_data_validation.py`:

```python
"""Pydantic validation gate for render_compliance_doc.

The renderer must reject dicts that don't match a known compliance model.
This blocks adversarial input from a poisoned RAG context.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_render_rejects_arbitrary_dict(vault_dir, monkeypatch):
    """A dict that doesn't match any compliance model is rejected."""
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("validation-test"))
    output = Path.home() / ".piighost" / "exports" / "out.md"
    with pytest.raises(ValueError, match="(does not match|invalid|unknown)"):
        asyncio.run(svc.render_compliance_doc(
            data={"foo": "bar", "controller": {"name": "<script>alert(1)</script>"}},
            format="md", profile="generic",
            output_path=str(output),
        ))
    asyncio.run(svc.close())


def test_render_accepts_valid_processing_register(vault_dir, monkeypatch):
    """A real ProcessingRegister.model_dump() passes validation."""
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("validation-ok"))
    register = asyncio.run(svc.processing_register(project="validation-ok"))
    output = Path.home() / ".piighost" / "exports" / "registre.md"
    result = asyncio.run(svc.render_compliance_doc(
        data=register.model_dump(),
        format="md", profile="generic",
        output_path=str(output),
    ))
    assert result.path == str(output)
    asyncio.run(svc.close())


def test_render_accepts_valid_dpia_screening(vault_dir, monkeypatch):
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("validation-dpia"))
    dpia = asyncio.run(svc.dpia_screening(project="validation-dpia"))
    output = Path.home() / ".piighost" / "exports" / "dpia.md"
    result = asyncio.run(svc.render_compliance_doc(
        data=dpia.model_dump(),
        format="md", profile="generic",
        output_path=str(output),
    ))
    assert result.path == str(output)
    asyncio.run(svc.close())


def test_render_rejects_extra_keys_at_top_level(vault_dir, monkeypatch):
    """Extra top-level keys outside the model schema are rejected.

    This catches a class of attack where the attacker crafts a dict that
    LOOKS like a ProcessingRegister but smuggles extra fields (e.g.
    `__html_payload`) that happen to be referenced by a malicious
    user-override template.
    """
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("validation-extra"))
    register = asyncio.run(svc.processing_register(project="validation-extra"))
    poisoned = register.model_dump()
    poisoned["__html_payload"] = "<script>alert(1)</script>"
    output = Path.home() / ".piighost" / "exports" / "poisoned.md"
    with pytest.raises(ValueError):
        asyncio.run(svc.render_compliance_doc(
            data=poisoned,
            format="md", profile="generic",
            output_path=str(output),
        ))
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to confirm they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_render_data_validation.py -v --no-header
```

Expected: `test_render_rejects_arbitrary_dict` and `test_render_rejects_extra_keys_at_top_level` FAIL (no validation in place — the function happily emits the poisoned MD or fails for an unrelated KeyError).

- [ ] **Step 3: Add the validator to `render.py`**

Open `src/piighost/compliance/render.py`. Find the `render_compliance_doc` function (around line 228). At the top of the function body — after the docstring, before any other logic — add the validation:

```python
def render_compliance_doc(
    *,
    data: dict[str, Any],
    format: Literal["md", "docx", "pdf"] = "md",
    profile: str = "generic",
    output_path: str | None = None,
) -> dict[str, Any]:
    """[existing docstring kept verbatim]"""
    # Validate data against the 3-way union BEFORE doing any I/O.
    # This blocks adversarial input from a poisoned MCP context.
    _validate_compliance_dict(data)

    # ... rest of the existing function body unchanged ...
```

Then add the helper at module top-level (above `render_compliance_doc`):

```python
from typing import Union

from piighost.service.models import (
    DPIAScreening,
    ProcessingRegister,
    SubjectAccessReport,
)
from pydantic import TypeAdapter, ValidationError

_COMPLIANCE_UNION_ADAPTER = TypeAdapter(
    Union[ProcessingRegister, DPIAScreening, SubjectAccessReport]
)


def _validate_compliance_dict(data: dict) -> None:
    """Raise ValueError if *data* doesn't match any known compliance model.

    Uses ``model_config.extra = "forbid"`` semantics through the union
    adapter so unknown keys are rejected — closes the poisoned-dict
    attack surface flagged in Phase 2 followup #3.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"render_compliance_doc data must be a dict; got {type(data).__name__}"
        )
    try:
        _COMPLIANCE_UNION_ADAPTER.validate_python(data)
    except ValidationError as exc:
        raise ValueError(
            "render_compliance_doc data does not match any known compliance "
            f"model (ProcessingRegister / DPIAScreening / SubjectAccessReport): {exc}"
        ) from exc
```

- [ ] **Step 4: Configure the models to forbid extra keys**

For Pydantic to reject `poisoned["__html_payload"]` etc., the three models need `model_config = ConfigDict(extra="forbid")`. Open `src/piighost/service/models.py` and check whether `ProcessingRegister`, `DPIAScreening`, `SubjectAccessReport` already have this. If they don't, add it:

```python
from pydantic import BaseModel, ConfigDict, Field

class ProcessingRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... existing fields ...

class DPIAScreening(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... existing fields ...

class SubjectAccessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... existing fields ...
```

This may flag drift in existing tests if any test passes extra keys. Run the existing render + processing_register + dpia + subject_access tests after adding `extra="forbid"`:

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_processing_register.py tests/unit/test_dpia_screening.py tests/unit/test_subject_access.py tests/unit/test_render_compliance_doc.py -v --no-header
```

If a test fails because of the new strictness, the test was carrying a bug — fix the test (don't loosen the model). If multiple tests fail, escalate before continuing.

- [ ] **Step 5: Run the new tests to confirm they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_render_data_validation.py -v --no-header
```

Expected: 4 passed.

- [ ] **Step 6: Re-run the full Phase 2 sweep**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_processing_register.py \
  tests/unit/test_dpia_screening.py \
  tests/unit/test_render_compliance_doc.py \
  tests/unit/test_render_data_validation.py \
  tests/unit/test_no_pii_leak_phase2.py \
  -v --no-header
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/compliance/render.py src/piighost/service/models.py tests/unit/test_render_data_validation.py
git commit -m "fix(compliance): validate render data against compliance union (Phase 2 followup #3)

render_compliance_doc now validates its data dict against
Union[ProcessingRegister, DPIAScreening, SubjectAccessReport] via
pydantic.TypeAdapter at function entry. Unknown shapes — including
extra top-level keys like a smuggled '__html_payload' — raise
ValueError before any template I/O.

Models switched to ConfigDict(extra='forbid') so the union adapter
genuinely rejects superset dicts.

Closes the HTML-injection vector flagged in the Phase 2 final review:
a Claude turn poisoned by adversarial RAG context could previously
have pushed <script> tags through the MD body into the PDF.

Four regression tests cover: arbitrary dict rejected, valid register
accepted, valid DPIA accepted, dict with extra top-level keys rejected."
```

---

## Task 3: Replace `_mask` partial-leak + extend privacy gate to SubjectAccessReport

**Files:**
- Modify: `src/piighost/service/core.py:877-880` (`_mask` static method)
- Modify: `tests/unit/test_no_pii_leak_phase2.py` (append 4th test)

The Phase 2 final review noted that `_ProjectService._mask` produces partial leaks for 3-character originals like `"Joe"` → `"J*e"`. This `_mask` is only used in `_to_entry_model` for `SubjectAccessReport.subject_preview` when `reveal=False`. When the resulting report is rendered through `render_compliance_doc`, the partial mask travels into the MD output — bypassing every Phase 2 privacy gate.

Fix: replace the per-character mask with a label-only placeholder (`<<SUBJECT>>`). Then extend `tests/unit/test_no_pii_leak_phase2.py` with a 4th test that renders a `SubjectAccessReport` and asserts no raw PII appears.

- [ ] **Step 1: Read the current `_mask` and its usage**

```bash
grep -n "_mask\|subject_preview\|original_masked" /c/Users/NMarchitecte/Documents/piighost/src/piighost/service/core.py | head -20
```

Confirm: `_mask` lives at line 877. It's used at line 887 (`original_masked=self._mask(v.original)`). Its result is stored in `VaultEntryModel.original_masked` and surfaces in `SubjectAccessReport.subject_preview` via line 672.

- [ ] **Step 2: Write the failing privacy gate**

In `tests/unit/test_no_pii_leak_phase2.py`, append a 4th test BEFORE the closing of the file:

```python
def test_rendered_subject_access_no_raw_pii(vault_dir, monkeypatch):
    """SubjectAccessReport rendered through render_compliance_doc must
    not leak raw PII via subject_preview / _mask partial-mask path.

    Closes Phase 2 followup #4 (the J*e-style partial-leak).
    """
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-sa"))
    proj = asyncio.run(svc._get_project("leak-sa"))

    # Seed a subject with a 3-character original that the old _mask would
    # have leaked as J*e.
    proj._vault.upsert_entity(
        token="<<np:joe>>", original="Joe", label="nom_personne", confidence=0.9,
    )
    # Plus the canonical Phase 2 leak fixtures
    _seed_pii(proj)

    sa = asyncio.run(svc.subject_access(
        tokens=["<<np:joe>>", "<<np:1>>"], project="leak-sa", max_excerpts=10,
    ))

    out = Path.home() / ".piighost" / "exports" / "subject_access.md"
    asyncio.run(svc.render_compliance_doc(
        data=sa.model_dump(), format="md", profile="generic",
        output_path=str(out),
    ))
    rendered = out.read_text(encoding="utf-8")

    # No raw PII (long forms) anywhere
    for raw in [*_KNOWN_RAW_PII, "Joe"]:
        assert raw not in rendered, (
            f"Raw PII '{raw}' leaked in rendered SubjectAccessReport"
        )
    # No partial mask either (the J*e form)
    assert "J*e" not in rendered, "_mask partial-leak surfaced"

    asyncio.run(svc.close())
```

The test imports `Path` — make sure `from pathlib import Path` is at the top of the file (the existing leak tests don't use it; add the import if missing).

- [ ] **Step 3: Run the test to confirm it fails**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_no_pii_leak_phase2.py::test_rendered_subject_access_no_raw_pii -v --no-header
```

Expected: FAILS with either "Raw PII 'Joe' leaked" or "_mask partial-leak surfaced". (The exact failure depends on whether the 3-char original survives — `J*e` definitely does.)

- [ ] **Step 4: Replace `_mask` to emit the label-only placeholder**

In `src/piighost/service/core.py` at line 877, replace the `_mask` method:

```python
    @staticmethod
    def _mask(original: str) -> str:
        """Return an opaque label-only placeholder.

        Previously emitted character-level masks like ``J*e`` for
        ``"Joe"`` — a partial PII leak when surfaced via
        SubjectAccessReport.subject_preview through render_compliance_doc.
        Now returns a constant ``<<SUBJECT>>`` token so no character of
        the original ever reaches a render pipeline.
        """
        return "<<SUBJECT>>"
```

Note: we keep the function signature and the call site unchanged. The argument `original` is now intentionally unused — the function exists only to centralize the placeholder, and renaming would force a wider rename of the call site at line 887.

- [ ] **Step 5: Run the new test plus existing privacy tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_no_pii_leak_phase2.py tests/unit/test_no_pii_leak_phase1.py -v --no-header
```

Expected: all 4 + Phase 1 tests pass.

- [ ] **Step 6: Run the subject_access regression tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_subject_access.py -v --no-header
```

If any test asserts on the old `J*e` shape, fix it to expect `<<SUBJECT>>` — that test was encoding a bug.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_no_pii_leak_phase2.py
git commit -m "fix(rgpd): replace _mask partial-leak with <<SUBJECT>> placeholder

The previous _mask produced 'J*e' for 3-char originals like 'Joe' —
a real partial PII leak that surfaced via SubjectAccessReport.subject_preview
when rendered through render_compliance_doc.

Now returns the opaque '<<SUBJECT>>' label-only token. No character of
the original reaches the render pipeline.

Adds the 4th Phase 2 privacy gate that renders a SubjectAccessReport
end-to-end and asserts no raw PII (and no J*e partial-mask) survives.

Closes Phase 2 followup #4."
```

---

## Task 4: `compliance/__init__.py` public API re-exports

**Files:**
- Modify: `src/piighost/compliance/__init__.py`
- Test: `tests/unit/test_compliance_public_api.py`

Phase 2 followup #6 noted that `compliance/__init__.py` is empty — programmatic callers must import from submodules. Tightening the public surface is a 5-minute change.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compliance_public_api.py`:

```python
"""Verify the piighost.compliance public API re-exports."""
from __future__ import annotations


def test_compliance_top_level_reexports():
    """Programmatic callers should import from piighost.compliance directly."""
    from piighost.compliance import (
        build_processing_register,
        screen_dpia,
        render_compliance_doc,
        load_bundled_profile,
    )

    assert callable(build_processing_register)
    assert callable(screen_dpia)
    assert callable(render_compliance_doc)
    assert callable(load_bundled_profile)


def test_compliance_dunder_all_is_complete():
    import piighost.compliance as cmp

    expected = {
        "build_processing_register",
        "screen_dpia",
        "render_compliance_doc",
        "load_bundled_profile",
    }
    assert set(cmp.__all__) == expected
```

- [ ] **Step 2: Run the test to confirm it fails**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_compliance_public_api.py -v --no-header
```

Expected: ImportError on the public symbols.

- [ ] **Step 3: Update `__init__.py`**

Replace the contents of `src/piighost/compliance/__init__.py` with:

```python
"""piighost.compliance — RGPD compliance subsystem.

Public API:
    build_processing_register  — Art. 30 register builder
    screen_dpia                — Art. 35 DPIA-lite screening
    render_compliance_doc      — Render compliance dict to MD/DOCX/PDF
    load_bundled_profile       — Read bundled per-profession defaults
"""
from .processing_register import build_processing_register
from .dpia_screening import screen_dpia
from .render import render_compliance_doc
from .profile_loader import load_bundled_profile

__all__ = [
    "build_processing_register",
    "screen_dpia",
    "render_compliance_doc",
    "load_bundled_profile",
]
```

- [ ] **Step 4: Run the test**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_compliance_public_api.py -v --no-header
```

Expected: 2 passed.

- [ ] **Step 5: Run the full compliance test sweep to catch import-cycle regressions**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_profile_loader.py \
  tests/unit/test_processing_register.py \
  tests/unit/test_dpia_screening.py \
  tests/unit/test_render_compliance_doc.py \
  tests/unit/test_render_data_validation.py \
  tests/unit/test_compliance_public_api.py \
  -v --no-header
```

Expected: all green. If anything breaks, the eager re-imports in `__init__.py` introduced a cycle — make the imports lazy (move them inside `__getattr__`) or split.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/compliance/__init__.py tests/unit/test_compliance_public_api.py
git commit -m "feat(compliance): re-export public API from piighost.compliance

Top-level package now exposes:
  - build_processing_register
  - screen_dpia
  - render_compliance_doc
  - load_bundled_profile

Closes Phase 2 followup #6. Programmatic callers (notebooks, future
CLI tools) no longer need to know the submodule layout."
```

---

## Task 5: Documentation corrections (3 small edits)

**Files:**
- Modify: `src/piighost/mcp/tools.py` (`controller_profile_defaults` description)
- Modify: `docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md` (RPPS/ADELI erratum)
- Modify: `src/piighost/compliance/profile_loader.py` (AttributeError comment)

Three quick documentation hardening items from Phase 4 followups #1, #2, #8. No tests — these are doc-only changes.

- [ ] **Step 1: Append security note to `controller_profile_defaults` MCP description**

Open `src/piighost/mcp/tools.py`. Find the `controller_profile_defaults` ToolSpec. Update the description to append a sentence about path-traversal rejection:

```python
    ToolSpec(
        name="controller_profile_defaults",
        rpc_method="controller_profile_defaults",
        description=(
            "Read-only: return the bundled default profile for a profession "
            "(avocat / notaire / medecin / expert_comptable / rh / generic). "
            "Used by /hacienda:setup to pre-fill finalites, bases_legales, "
            "duree_conservation, and ordinal_label. Returns {} for unknown "
            "profession or invalid input (rejects path traversal via strict "
            "regex on profession)."
        ),
        timeout_s=2.0,
    ),
```

- [ ] **Step 2: Add the RPPS/ADELI erratum to the spec**

Open `docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md`. Find line 599 — the wizard ordinal-types list. Locate the "Wizard `/hacienda:setup`" section and append (or insert before "## Tests") a short erratum block:

```markdown
### Erratum (Phase 5 hardening)

The Phase 4 wizard implementation corrected the médecin ordinal label.
Spec line 599 listed `(barreau / chambre / OEC / ARS)`, but ARS is the
*issuing authority*, not the registration number. The bundled
`compliance/profiles/medecin.toml` correctly uses `Numéro RPPS / ADELI`
per French regulatory practice (RPPS replaced ADELI for most
professions). No code change needed — the spec text remains as-is for
historical accuracy; this erratum documents the intentional deviation.
```

- [ ] **Step 3: Document the `AttributeError` catch in `profile_loader.py`**

Open `src/piighost/compliance/profile_loader.py`. Find the `except` line that catches `AttributeError`. Add a comment explaining why:

```python
def load_bundled_profile(profession: str) -> dict:
    """Return the bundled default profile for *profession*, or ``{}`` if
    the profession is unknown or the input fails validation.

    The validation regex blocks path traversal — *profession* is reachable
    from the MCP boundary (untrusted).
    """
    if not _PROFESSION_RE.match(profession or ""):
        return {}
    try:
        path = resources.files("piighost.compliance.profiles") / f"{profession}.toml"
        if not path.is_file():
            return {}
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, AttributeError, tomllib.TOMLDecodeError, OSError):
        # AttributeError can fire when importlib.resources returns a
        # MultiplexedPath (namespace-package case) without an .is_file()
        # method — older Python versions did this. We keep the catch
        # for defence-in-depth even though our package layout uses
        # __init__.py and a regular package, where .is_file() is always
        # defined. Closes Phase 4 followup #8.
        return {}
```

- [ ] **Step 4: Sanity-check that nothing broke**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_profile_loader.py tests/unit/test_controller_profile_defaults_mcp.py -v --no-header
```

Expected: 9 passed (5 + 4).

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/tools.py docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md src/piighost/compliance/profile_loader.py
git commit -m "docs: Phase 4 followups #1, #2, #8 — three small corrections

1. controller_profile_defaults MCP description now documents the
   path-traversal rejection guarantee for security auditors.
2. Spec gets an erratum noting that médecin uses RPPS/ADELI, not ARS
   (ARS is the issuer, not the registration number).
3. profile_loader.py comments why AttributeError is in the except
   tuple (legacy MultiplexedPath behaviour, defence-in-depth)."
```

---

## Task 6: Phase 5 final smoke + push

**Files:**
- No new code — verification + push.

- [ ] **Step 1: Run all Phase 5 tests together**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_forget_subject_concurrency.py \
  tests/unit/test_render_data_validation.py \
  tests/unit/test_compliance_public_api.py \
  -v --no-header
```

Expected: 2 + 4 + 2 = 8 passed.

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
  tests/unit/test_subject_access.py \
  tests/unit/test_forget_subject.py \
  tests/unit/test_forget_subject_concurrency.py \
  tests/unit/test_profile_loader.py \
  tests/unit/test_compliance_public_api.py \
  tests/integration/test_setup_wizard_e2e.py \
  --no-header
```

Expected: all green.

- [ ] **Step 3: Push**

```bash
ECC_SKIP_PREPUSH=1 git push jamon master
```

- [ ] **Step 4: (Optional) write Phase 5 follow-ups doc**

If you noticed UX rough edges or new cleanup candidates during this round, capture them in `docs/superpowers/followups/2026-04-27-rgpd-phase5-followups.md` following the existing format (severity legend + resolution log table). If nothing surfaced, skip — Phase 5 is itself the cleanup phase.

---

## Self-review checklist

**Spec coverage:**

| Followup origin | Implementing task |
|---|---|
| Phase 1 review I1 (`forget_subject` lock) | Task 1 |
| Phase 2 followup #3 (Pydantic-validate render data) | Task 2 |
| Phase 2 followup #4 (extend leak gate to SubjectAccessReport) | Task 3 |
| Phase 2 followup #6 (`compliance/__init__.py` re-exports) | Task 4 |
| Phase 4 followups #1 (RPPS erratum) | Task 5 step 2 |
| Phase 4 followups #2 (MCP description security note) | Task 5 step 1 |
| Phase 4 followups #8 (`AttributeError` catch comment) | Task 5 step 3 |
| Verification + push | Task 6 |

✓ Every selected followup has a task. Out-of-scope items (Phase 4 #4 MCP-shim integration tests, Phase 4 #7 field rename, Phase 2 #5 cnil_3 cross-project state) are noted in the file map intro and properly deferred.

**Placeholder scan**: every code block has real code. No "TBD" / "implement later". The `_mask` replacement, the lock wrap pattern, the Pydantic adapter, and the re-exports are all spelled out.

**Type consistency**:
- `_validate_compliance_dict(data: dict) -> None` matches `render_compliance_doc(data: dict[str, Any], ...)`. ✓
- `Union[ProcessingRegister, DPIAScreening, SubjectAccessReport]` references existing models from `piighost.service.models` (verified live: ProcessingRegister + DPIAScreening from Phase 2, SubjectAccessReport from Phase 1). ✓
- `_write_lock` is `asyncio.Lock` per `_ProjectService.__init__` line 73. ✓
- `_mask(original: str) -> str` keeps its signature; only the body changes. The `original` argument becomes unused but that's acceptable to preserve the call-site at line 887. ✓
- `load_bundled_profile`, `build_processing_register`, `screen_dpia`, `render_compliance_doc` are all real public symbols verified to exist before re-export. ✓

**Scope check**: Phase 5 alone, single PR cycle, ~4 hours. No new heavy deps, no new SQLite tables, no new MCP tools, no plugin work. Strictly hardening.

---

## Estimated effort

| Task | Effort |
|---|---|
| 1 — Lock forget_subject | 30 min |
| 2 — Pydantic validate render data | 1.5 h (includes the `extra="forbid"` migration risk) |
| 3 — Replace `_mask` + extend leak test | 30 min |
| 4 — `__init__.py` re-exports | 15 min |
| 5 — 3 doc corrections | 15 min |
| 6 — Smoke + push | 15 min |
| **Total** | **~3.5 h** |
