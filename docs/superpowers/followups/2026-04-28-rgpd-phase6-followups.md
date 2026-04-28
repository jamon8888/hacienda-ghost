# RGPD Phase 6 — Follow-up Issues

**Date:** 2026-04-28
**Source:** Final code review of Phase 6 (commits `3129062..383ede0`)
**Plan:** [docs/superpowers/plans/2026-04-28-rgpd-phase6-cleanup.md](../plans/2026-04-28-rgpd-phase6-cleanup.md) (`3129062`)

This file collects issues found during the final code review that were deliberately **not** fixed before push. Each entry has enough context that a future engineer can pick it up cold.

Severity legend:

- 🟢 **NICE-TO-HAVE** — track loosely; close if priorities shift

(No 🟡 Important items remain after Phase 6 — the reviewer's two `Important` flags were addressed inline in commit `383ede0`.)

---

## 🟢 1. `test_unknown_attribute_raises_attribute_error` should use `pytest.raises`

**File:** `tests/unit/test_compliance_lazy_imports.py` last test

```python
def test_unknown_attribute_raises_attribute_error():
    import piighost.compliance as cmp
    try:
        _ = cmp.nonexistent_function
    except AttributeError as exc:
        assert "nonexistent_function" in str(exc)
    else:
        raise AssertionError("AttributeError not raised")
```

The try/except/else pattern is correct but inconsistent with the rest of the codebase. One-line replacement:

```python
def test_unknown_attribute_raises_attribute_error():
    import piighost.compliance as cmp
    with pytest.raises(AttributeError, match="nonexistent_function"):
        _ = cmp.nonexistent_function
```

Estimated effort: 2 minutes.

---

## 🟢 2. Expand `_PARTY_LABEL_MAP` with notarial / CRM aliases

**File:** `src/piighost/compliance/processing_register.py:165-179`

The map covers the obvious French + a couple of English variants but misses several common labels for the regulated professions. Worth adding:

- `héritier` / `heritier` → `héritiers` (notarial files)
- `prospect` / `prospects` → `prospects` (CRM)
- `representant_legal` / `mandataire` → `représentants légaux`

Médecin/notaire/EC themselves are *actors* (the writer of the registre), not data subjects, so their absence is intentional and correct.

Not blocking — the "unknown surfaces as-is" branch (now covered by `test_register_data_subjects_unknown_label_surfaces_as_is` in `383ede0`) handles them — but the avocat reviewing the registre will see un-normalized labels for these common cases.

Estimated effort: 5 minutes (add to map + 1–2 parametrized assertions).

---

## 🟢 3. `test_corrupt_bundled_toml_emits_warning` could explain its `Path` substitution

**File:** `tests/unit/test_profile_loader_warns.py:21-27`

The test monkeypatches `plm.resources` to a `_FakeResources` whose `.files()` returns a `pathlib.Path`, not a `MultiplexedPath`. This works because `Path.is_file()` and `Path.read_text()` exist (duck-typing), so the `tomllib.loads()` call fires and raises `TOMLDecodeError`.

Adding a 1-line comment would help the next reader avoid the "what about AttributeError on `.is_file()`?" rabbit hole:

```python
class _FakeResources:
    @staticmethod
    def files(_):
        # pathlib.Path duck-types MultiplexedPath's .is_file()/.read_text()
        # well enough for our loader's happy path. The test exercises the
        # TOMLDecodeError branch, not the AttributeError branch.
        return bad_dir
```

Estimated effort: 2 minutes.

---

## 🟢 4. Fixture comment on `config.toml` workaround slightly mischaracterizes the daemon

**File:** `tests/integration/test_mcp_shim_compliance_e2e.py` fixture

The fixture writes `[reranker]\nbackend = "none"` to `vault_dir/config.toml` because `build_app` reads from there. The current inline comment says "daemon ignores PIIGHOST_DETECTOR/EMBEDDER env vars at startup" — but `PIIGHOST_DETECTOR=stub` IS read (by `service/core.py:1363`). It's just the **reranker** that has always been ServiceConfig-only.

Tightening the comment:

```python
# build_app reads vault_dir/config.toml for ServiceConfig — env vars
# control detector/embedder choice but the reranker is config-only.
# Without this, the default 'cross_encoder' backend triggers transformers
# import which breaks on this dev env.
```

Estimated effort: 2 minutes.

---

## 🟢 5. Top-level model `extra="forbid"` rejection is non-co-located

**File:** `tests/unit/test_compliance_submodels_forbid.py`

Phase 6 Task 2 covers the 12 sub-models. The 3 top-level models (`ProcessingRegister`, `DPIAScreening`, `SubjectAccessReport`) had `extra="forbid"` set in Phase 5 Task 2 and the rejection IS exercised by `test_render_rejects_extra_keys_at_top_level` in `tests/unit/test_render_data_validation.py`.

Coverage exists, just not co-located. A future tidying could either:
- Add the 3 top-level models to the parametrized test in `test_compliance_submodels_forbid.py`.
- Or rename that file to `test_compliance_models_forbid.py` and add explicit parametrize entries.

Not blocking — the pre-push regression sweep already exercises both paths. Pure organization.

Estimated effort: 5 minutes if combined with #1 above.

---

## 🟢 6. `ForgetReport` and `DocumentMetadata` lack `extra="forbid"`

**File:** `src/piighost/service/models.py`

These models are not part of the render union (the smuggled-key threat model targeted in Phase 5 Task 2 + Phase 6 Task 2), so their absence is technically correct for that scope. But they're consumed by other surfaces:

- `ForgetReport` is returned by `forget_subject` — reachable from MCP.
- `DocumentMetadata` is consumed by `processing_register` and `subject_access` indirectly.

If we ever wire either of these through `render_compliance_doc` or expose them more directly to MCP callers, the `extra="forbid"` posture should extend there too. Track loosely.

Estimated effort: 10 minutes (flip + parametrized regression + verify no test breaks).

---

## Resolution log

| # | Issue | Status | Resolution |
|---|---|---|---|
| 1 | Use `pytest.raises` for unknown-attribute test | open | — |
| 2 | Expand `_PARTY_LABEL_MAP` with notarial/CRM aliases | open | — |
| 3 | Document `Path` duck-typing in profile_loader test | open | — |
| 4 | Tighten config.toml fixture comment | open | — |
| 5 | Co-locate top-level model `extra="forbid"` test | open | — |
| 6 | `ForgetReport` / `DocumentMetadata` `extra="forbid"` | open | scope-correct as-is |

(Reviewer's Important #3 "over-permissive `or` assertions" and Important #4 "unknown-label test gap" addressed inline in `383ede0`, not deferred.)
