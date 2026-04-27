# RGPD Phase 2 — Follow-up Issues

**Date:** 2026-04-27
**Source:** Final code review of Phase 2 (commits `6893970..64de0cb` on master)
**Spec:** [docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md](../specs/2026-04-27-rgpd-compliance-design.md) (`a2535c3`)
**Plan:** [docs/superpowers/plans/2026-04-27-rgpd-phase2-registre-dpia-render.md](../plans/2026-04-27-rgpd-phase2-registre-dpia-render.md) (`fb5d960`)

This file collects issues found during the final code review that were deliberately **not** fixed before push. Each entry has enough context that a future engineer (or a future you) can pick it up cold.

Severity legend:

- 🔴 **CRITICAL** — block on or before next release
- 🟡 **IMPORTANT** — should be addressed in a follow-up PR within a release or two
- 🟢 **NICE-TO-HAVE** — track loosely; close if priorities shift

---

## 🟡 1. Lock `forget_subject` per project (Phase 1 carryover I1)

**File:** `src/piighost/service/core.py` — `_ProjectService.forget_subject`

Phase 1 left this open: the Art. 17 forget cascade (vault delete → chunk rewrite → audit) is not protected by `self._write_lock`. A concurrent `forget_subject` from another caller, or a `query`/`index_path` racing with the chunk rewrite, can produce a partially-rewritten state.

Phase 2 plan flagged this as "(Optional) Bonus" in Task 9 and the optional bonus was not done.

**Fix:** wrap the body of `forget_subject` (after `start = time.monotonic()`, before vault deletes + chunk rewrite) with `async with self._write_lock:`. Add a regression test that fires two `forget_subject` calls concurrently against a seeded vault and asserts a single, consistent post-state.

Estimated effort: ~30 minutes.

---

## 🟡 2. SKILL.md output_path examples now use the default — verify in production

**Files:**
- `.worktrees/hacienda-plugin/skills/rgpd-registre/SKILL.md`
- `.worktrees/hacienda-plugin/skills/rgpd-dpia/SKILL.md`

Plugin commit `8ae7419` dropped the `output_path="<folder>/..."` argument from the example calls so the daemon falls back to `~/.piighost/exports/<project>-<doctype>-<ts>.<ext>`. Reasoning: Task 5 hardening (piighost `ec79529`) constrains `output_path` to live under `~/.piighost/`.

The current text instructs Claude to omit `output_path` and tells the user where the file lands. Verify in a real Cowork session that:
1. The user actually finds the generated file (default location may be surprising).
2. If the user explicitly requests a Cowork-folder output (e.g. "save it next to the dossier"), the skill correctly explains the security constraint instead of producing a broken call.

Long-term, consider adding a per-folder export-path opt-in via `controller_profile` so power users can write outputs into the Cowork folder without compromising the default sandbox.

Estimated effort: usability check, ~1 hour. Opt-in mechanism, ~3 hours.

---

## 🟡 3. Pydantic-validate `data: dict` at the `render_compliance_doc` MCP boundary

**File:** `src/piighost/compliance/render.py` — `render_compliance_doc(data: dict, ...)`

The function takes `data: dict[str, Any]` and dispatches to a template based on heuristic key-set scoring (`_DOCTYPE_MARKERS`). At the MCP boundary an untrusted caller (or a Claude turn poisoned by adversarial RAG context) can pass an arbitrary dict.

Templates currently render with `autoescape=False` (correct for Markdown), so a `controller.name` like `<script>alert(1)</script>` would land literally in the MD. That's safe in the MD output, but the PDF path goes MD → HTML (via the `markdown` lib) → PDF (weasyprint). HTML in the markdown body bypasses Markdown sanitization and renders as live HTML in the PDF. Weasyprint disables JS by default, so this is layout-corruption / phishing-vector territory rather than RCE — but still wrong.

**Fix:** at the function entry, validate `data` against `Union[ProcessingRegister, DPIAScreening, SubjectAccessReport]` via `pydantic.TypeAdapter`. Use `model_validate` (not `model_validate_json`) since `data` is already a dict. Reject unknown shapes with `ValueError`.

Bonus: also escape user-controlled string fields when targeting PDF, e.g. via a Jinja filter `e | replace("<", "&lt;")`.

Estimated effort: ~1.5 hours (validate + targeted test that passes a poisoned dict and expects ValueError).

---

## 🟡 4. Phase 2 no-PII-leak test does not cover SubjectAccessReport rendering

**File:** `tests/unit/test_no_pii_leak_phase2.py`

`test_rendered_md_no_raw_pii` only renders a `ProcessingRegister`. The render layer also exposes `subject_access` via `generic/subject_access.md.j2`, which consumes a `SubjectAccessReport` (Phase 1 type) — a path Phase 1's own leak tests do exercise at the data layer, but **not** through the Phase 2 render layer.

Specifically: `core.py` builds `subject_preview` via `f"{raw[0]}{'*' * (len(raw) - 2)}{raw[-1]}"`. For 3-char originals like `"Joe"` this returns `"J*e"` — a meaningful partial leak that the current invariant tests don't cover when rendered.

**Fix:** add a fourth test to `test_no_pii_leak_phase2.py` that:
1. Seeds the same 4 PII strings.
2. Calls `subject_access(tokens=[...])`.
3. Renders the result via `render_compliance_doc(format="md", profile="generic")`.
4. Asserts none of the raw strings appear in the rendered MD.

If the test fails, fix `_mask` in `core.py` to use `"<<SUBJECT>>"` placeholders instead of `J*e`-style partial masks. (This was raised in the Phase 2 final review but pre-dates Phase 2.)

Estimated effort: ~30 minutes for the test, +1 hour if `_mask` needs replacing.

---

## 🟢 5. CNIL DPIA criteria 1, 3, 6 not implemented

**File:** `src/piighost/compliance/dpia_screening.py` (docstring already documents the omissions)

Phase 2 covers 6 of the 9 CNIL criteria (`art35.3.b`, `cnil_2`, `cnil_4`, `cnil_5`, `cnil_7`, `cnil_9`). Deliberately deferred:

- **`cnil_3` (recoupement de fichiers)** — would require state crossing the per-project isolation boundary, e.g. detecting that "Marie Dupont" appears in both `client-acme` and `client-zeta` projects. Implementing this needs either a global cross-project entity index or an explicit user-driven cross-project query.
- **`cnil_1` (évaluation/scoring)** — requires intent-labelling on the documents themselves (is this a credit-scoring report? a recruitment ranking?). Out of reach with our current heuristic doc_type classifier; would need a fine-tuned classifier or LLM-assisted labelling.
- **`cnil_6` (exclusion d'un service)** — out of scope for the regulated professions targeted in this phase (avocats, notaires, médecins, experts-comptables, RH).

Track for a future phase if a regulated user explicitly asks for any of these.

Estimated effort: `cnil_3` ~1 day; `cnil_1` ~3 days (depends on classifier quality); `cnil_6` not planned.

---

## 🟢 6. `compliance/__init__.py` doesn't re-export the public API

**File:** `src/piighost/compliance/__init__.py`

Currently empty. Programmatic callers have to import from submodules (`from piighost.compliance.processing_register import build_processing_register`). Adding:

```python
from .processing_register import build_processing_register
from .dpia_screening import screen_dpia
from .render import render_compliance_doc

__all__ = ["build_processing_register", "screen_dpia", "render_compliance_doc"]
```

would tighten the public surface and make the package shape obvious. Defer until there's a non-MCP caller (e.g. a CLI tool or a notebook).

Estimated effort: 5 minutes when needed.

---

## 🟢 7. `_classify_data_subjects` heuristic ignores `parties` from `documents_meta`

**File:** `src/piighost/compliance/processing_register.py:163`

The current heuristic only inspects the project name (`startswith("client")` / `startswith("dossier")`) and a few RH keywords. It doesn't consult the `parties_json` column from `documents_meta`, even though that data is collected at index time.

A real avocat seeing `data_subject_categories: ["clients"]` on a project that actually contains employee complaints + client invoices would over-trust the registre.

**Fix:** read `parties_json` aggregates across the project's documents and surface the top categories (e.g. "salariés" if `controller.profession=="rh"` or if parties tags include employment terms). Add a `manual_field` hint flagging that auto-detection is best-effort.

Estimated effort: ~2 hours.

---

## 🟢 8. `profile` parameter naming ambiguity

**Files:** `src/piighost/compliance/processing_register.py`, `src/piighost/compliance/dpia_screening.py`, `src/piighost/compliance/render.py`, `src/piighost/service/core.py`

Two unrelated things share the `profile` namespace:

- The dict from `ControllerProfile` (`profile["controller"]["profession"]`)
- The template profile string (`profile="avocat"` in `render_compliance_doc`)

Calling sites flip between them within a few lines. A future reader will trip on it.

**Fix:** rename the controller-profile parameter to `controller_profile` in the compliance-builder signatures (keep `profile` for the template profile in `render_compliance_doc`). Or add a one-line docstring note in each affected function explaining which is which.

Estimated effort: 30 minutes for the rename + caller updates.

---

## 🟢 9. End-to-end MCP test missing for Phase 2 surface

The Phase 2 test sweep (27 tests) is unit-level — it bypasses the MCP shim, daemon dispatch, and JSON serialization round-trip.

A single integration test that:
1. Spawns the daemon.
2. Connects via the MCP shim.
3. Calls `processing_register` → `dpia_screening` → `render_compliance_doc` end-to-end.
4. Asserts the round-trip file lands in the expected location with no PII leak.

…would catch a class of bugs (JSON serialization, dispatcher param-name drift, FastMCP schema generation) that unit tests can't.

Estimated effort: ~3 hours including fixture setup and stable wait-for-daemon harness.

---

## Resolution log

| # | Issue | Status | Resolution |
|---|---|---|---|
| 1 | Lock `forget_subject` | open | — |
| 2 | SKILL.md output_path UX | open | — |
| 3 | Pydantic-validate render data | open | — |
| 4 | Leak test for SubjectAccess render | open | — |
| 5 | CNIL cnil_1/3/6 deferred | accepted | docstring `64de0cb` |
| 6 | `compliance/__init__.py` exports | open | — |
| 7 | `_classify_data_subjects` heuristic | open | — |
| 8 | `profile` naming ambiguity | open | — |
| 9 | Phase 2 MCP integration test | open | — |
