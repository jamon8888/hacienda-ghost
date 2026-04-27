# RGPD Phase 5 — Follow-up Issues

**Date:** 2026-04-27
**Source:** Final code review of Phase 5 (commits `ac08d2d..6c9e25c`)
**Plan:** [docs/superpowers/plans/2026-04-27-rgpd-phase5-hardening.md](../plans/2026-04-27-rgpd-phase5-hardening.md) (`ac08d2d`)

This file collects issues found during the final code review that were deliberately **not** fixed before push (or surfaced during execution and deferred). Each entry has enough context that a future engineer can pick it up cold.

Severity legend:

- 🟡 **IMPORTANT** — should be addressed in a follow-up PR within a release or two
- 🟢 **NICE-TO-HAVE** — track loosely; close if priorities shift

---

## 🟡 1. `compliance/__init__.py` eager imports add ~3s startup cost

**File:** `src/piighost/compliance/__init__.py` (commit `1551f82`)

The reviewer measured a 3246 ms cold first-import after switching to eager re-exports. Anyone doing `from piighost.compliance import load_bundled_profile` (a tiny TOML reader) now pays for `pydantic` + `service.models` + `render.py`'s top-level imports, even though `load_bundled_profile` itself has no such dependencies.

For the long-lived MCP daemon this is a one-time tax that doesn't matter. For:
- `piighost-mcp` cold-start latency
- CLI scripts that only use the loader
- Future test fixtures that import `compliance.profile_loader` lazily

…it could matter.

**Fix:** switch to lazy `__getattr__` per PEP 562. The plan even sketched the implementation as a fallback. Cost: ~10 minutes + verifying the existing tests still pass.

```python
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
    raise AttributeError(...)
```

Estimated effort: 30 minutes.

---

## 🟢 2. Apply `extra="forbid"` to compliance sub-models for explicit error reporting

**File:** `src/piighost/service/models.py`

Phase 5 commit `6c9e25c` already closes the actual exploit (the renderer now uses `validated.model_dump()` so smuggled keys can never reach Jinja). But the union adapter still silently *drops* unknown nested keys at validation time — no error is reported back to the caller.

For an MCP-driven flow, surfacing a `ValueError("unknown field: controller.__html_payload")` would help the operator notice malformed callers (or attackers) instead of letting the bad input round-trip through validation as if everything were fine.

Sub-models that would benefit:
- `ControllerInfo`, `DPOInfo` (set by the wizard / controller_profile)
- `DataCategoryItem`, `RetentionItem`, `TransferItem`, `SecurityMeasureItem`, `DocumentsSummary`, `ManualFieldHint` (built by `processing_register`)
- `DPIATrigger`, `CNILPIAInputs` (built by `dpia_screening`)
- `SubjectDocumentRef`, `SubjectExcerpt` (built by `subject_access`)

Add `model_config = ConfigDict(extra="forbid")` to each.

Risk: if any pre-existing test passes superset dicts at the sub-model layer (none currently do — verified during Phase 5 Task 2), this would surface as a test failure that needs fixing in the test (not the model).

Estimated effort: 15 minutes including verifying every pre-existing test still passes.

---

## 🟢 3. Pydantic union has no discriminator — error messages are verbose

**File:** `src/piighost/compliance/render.py:40-42`

```python
_COMPLIANCE_UNION_ADAPTER = TypeAdapter(
    Union[ProcessingRegister, DPIAScreening, SubjectAccessReport]
)
```

Today `_COMPLIANCE_UNION_ADAPTER.validate_python(bad_dict)` produces a `ValidationError` containing 3 mismatch reports concatenated, because Pydantic falls back to "smart union" (try each, pick first that validates). This is correct behaviour, just user-unfriendly when reading the error.

A `kind: Literal["registre", "dpia_screening", "subject_access"]` discriminator field on each model would let Pydantic dispatch to a single model and produce a focused error message.

Out of scope for Phase 5 because it requires a model schema bump (`v: Literal[1] = 1` already exists for versioning, but a separate `kind` would be needed for discrimination — they serve different purposes).

Estimated effort: 1 hour including migration test for backward-compat with existing serialized dumps.

---

## 🟢 4. `test_concurrent_forget_holds_write_lock` uses 100 ms sleep as the "blocked?" signal

**File:** `tests/unit/test_forget_subject_concurrency.py`

```python
await asyncio.sleep(0.1)
assert not forget_task.done(), "forget_subject did not respect _write_lock"
```

A 100 ms sleep is a practical proxy for "did the task block?" but could flake under loaded CI scheduling — especially on Windows. The reviewer suggested:

```python
with pytest.raises(asyncio.TimeoutError):
    await asyncio.wait_for(asyncio.shield(forget_task), timeout=0.05)
```

That gives an explicit timeout-as-signal rather than racing the scheduler. (Note `asyncio.shield` to prevent the timeout from cancelling the underlying forget — we want it to keep waiting on the lock.)

Estimated effort: 10 minutes.

---

## 🟢 5. `_mask` argument is dead code

**File:** `src/piighost/service/core.py:877-880` (commit `c0fa216`)

After centralizing all subject-preview masking onto `_mask`, the `original` argument is now unused. It exists only to preserve the signature for the existing call sites that pass `entry.original` / `v.original`. The implementer added `# noqa: ARG004` (unused static method argument) and a docstring explaining why.

If we ever re-introduce per-label placeholders (e.g. `<<SUBJECT:NOM>>` or `<<SUBJECT:EMAIL>>`), the argument becomes useful again. Until then, a stricter cleanup would be to make `_mask()` zero-arg and update the two call sites. Acceptable as-is.

Estimated effort: 5 minutes if we ever decide to clean it up.

---

## 🟢 6. `profile_loader.py` `MultiplexedPath` comment is slightly historical

**File:** `src/piighost/compliance/profile_loader.py` (commit `08de414`)

The new comment explains that `AttributeError` is caught for old `MultiplexedPath` behaviour from older Python layouts. Technically `MultiplexedPath` got `is_file()` in Python 3.10, so the catch is purely defence-in-depth on a 3.13+ codebase. The wording "older Python layouts did this" is fine — just noting that "older" means pre-3.10, which is now multiple years old.

If we ever drop pre-3.13 support entirely (we already require 3.11 for `tomllib`), the catch can be tightened.

Estimated effort: 5 minutes.

---

## Resolution log

| # | Issue | Status | Resolution |
|---|---|---|---|
| 1 | `compliance/__init__.py` eager imports add ~3s startup | open | — |
| 2 | Sub-models `extra="forbid"` for error visibility | open | exploit already closed in `6c9e25c` |
| 3 | Union has no discriminator | open | — |
| 4 | Concurrency test 100ms sleep proxy | open | — |
| 5 | `_mask` dead `original` arg | open | acceptable |
| 6 | `MultiplexedPath` comment wording | open | acceptable |
