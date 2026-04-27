# RGPD Phase 4 — Follow-up Issues

**Date:** 2026-04-27
**Source:** Final code review of Phase 4 (commits `63e8dbd..b9edda4` + plugin `f979e5a`)
**Spec:** [docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md](../specs/2026-04-27-rgpd-compliance-design.md) (`a2535c3`)
**Plan:** [docs/superpowers/plans/2026-04-27-rgpd-phase4-wizard-setup.md](../plans/2026-04-27-rgpd-phase4-wizard-setup.md) (`439bda8`)

This file collects issues found during the final code review that were deliberately **not** fixed before push. Each entry has enough context that a future engineer (or a future you) can pick it up cold.

Severity legend:

- 🟡 **IMPORTANT** — should be addressed in a follow-up PR within a release or two
- 🟢 **NICE-TO-HAVE** — track loosely; close if priorities shift

---

## 🟡 1. Document the spec deviation: médecin uses RPPS/ADELI, not ARS

**Files:**
- `src/piighost/compliance/profiles/medecin.toml` (`ordinal_label = "Numéro RPPS / ADELI"`)
- `docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md` line 599

The spec lists `(barreau / chambre / OEC / ARS)` as the four ordinal-number types the wizard handles. The bundled `medecin.toml` correctly uses `RPPS / ADELI` instead because **ARS is the issuing authority**, not the registration number. The deviation is correct French regulatory practice (RPPS replaced ADELI for most professions; the ARS issues but does not name the number).

**Fix:** add a one-line note to the spec marking the correction so future cross-checks aren't confused. Either edit the spec in place or add an erratum section.

Estimated effort: 5 minutes.

---

## 🟡 2. MCP tool description does not document the security guarantee

**File:** `src/piighost/mcp/tools.py` (the `controller_profile_defaults` ToolSpec)

Current description lists supported professions but doesn't mention the path-traversal protection. For users this is fine (they don't construct adversarial inputs), but security auditors reading the tool catalog will wonder what happens for malformed input.

**Fix:** append to the description:

```
"...Returns {} for unknown profession or invalid input (rejects path
traversal via strict regex on profession)."
```

Estimated effort: 5 minutes.

---

## 🟢 3. `profile_loader` silently swallows `TOMLDecodeError` and `OSError`

**File:** `src/piighost/compliance/profile_loader.py:35`

The bundled TOMLs are shipped in the wheel — a `TOMLDecodeError` would be a build-time bug, not a runtime issue worth swallowing. Same for `OSError` on a wheel-bundled file (would only fire on filesystem corruption).

**Fix options:**
- Let `tomllib.TOMLDecodeError` propagate (so a future broken bundled TOML fails CI loudly).
- Or add a `logger.warning("Bundled profile %s failed to parse: %s", profession, exc)` before returning `{}`.

Logged warning is the lowest-risk option. Defensible as-is, but a logged warning would help the next dev.

Estimated effort: 15 minutes.

---

## 🟢 4. Test file naming inconsistency

**File:** `tests/unit/test_controller_profile_defaults_mcp.py`

Named `_mcp.py` but tests the **service** layer (`PIIGhostService.controller_profile_defaults`), not the MCP shim layer (`mcp/shim.py:_lazy_dispatch`). The actual MCP-shim path is unverified by this test.

**Fix options:**
- Rename to `test_controller_profile_defaults_service.py` for clarity.
- OR add a true MCP-shim test that goes through `_lazy_dispatch` end-to-end (this would close more of Phase 2 followup #9 in one shot).

Option 2 is more valuable. Combine with the existing `tests/integration/test_setup_wizard_e2e.py` if it grows.

Estimated effort: 30 minutes for rename, ~2 hours for true MCP-shim test.

---

## 🟢 5. No test for partial-edit path in the wizard flow

**File:** `tests/integration/test_setup_wizard_e2e.py`

The wizard skill explicitly tells the model "Hold on to this dict — it pre-fills steps 3–6," but the integration test only exercises **accept-as-is** (user keeps all defaults) and **per-project override**. No test for partial-edit:

> User accepts only `finalites[0:2]`, drops `finalites[2]`, round-trip preserves the trimmed list.

This is a likely real-world flow (an avocat who only does conseil juridique might drop "Représentation devant les juridictions") and should be covered.

Estimated effort: 30 minutes.

---

## 🟢 6. `medecin.toml` introduces a new `bases_legales` token

**File:** `src/piighost/compliance/profiles/medecin.toml`

The token `"consentement_explicite"` does not appear elsewhere in the codebase (verified via grep). Phase 2 consumers treat `bases_legales` as opaque strings (`processing_register.py:124`), so no current consumer breaks.

If a future GDPR-vocabulary normalization (e.g., RGPD Art. 6 / Art. 9 token aliases) is introduced, this token will need to be either kept in the lexicon or migrated.

Track loosely — non-blocking unless we add a normalizer.

Estimated effort: dependent on the eventual normalizer design.

---

## 🟢 7. `controller.bar_or_order_number` field name is profession-specific

**Files:** all bundled profile TOMLs + `src/piighost/service/models.py` (`ControllerInfo.bar_or_order_number`)

The field is named after avocat/notaire-specific concepts ("bar" = barreau, "order" = ordre). For médecin (RPPS) and especially for non-ordinal professions (RH/generic), the name is awkward.

**Fix:** rename to `controller.registration_number` in a follow-up phase, with a backward-compat shim that reads the old key for one release.

Estimated effort: 1 hour for rename + shim + migration test.

---

## 🟢 8. `profile_loader.py` catches `AttributeError` — investigate why

**File:** `src/piighost/compliance/profile_loader.py:35`

The `except (FileNotFoundError, AttributeError, tomllib.TOMLDecodeError, OSError)` includes `AttributeError`. This was carried over from `render.py`'s loader. The reason in the original was `bundled_path.is_file()` may not exist on certain `MultiplexedPath` cases under namespace-packages. Verify whether it's still needed in 3.13 with a regular package layout, or document why we keep it.

Estimated effort: 30 minutes (verify or remove + comment).

---

## Resolution log

| # | Issue | Status | Resolution |
|---|---|---|---|
| 1 | Spec deviation (RPPS vs ARS) — document | open | — |
| 2 | MCP tool description missing security note | open | — |
| 3 | profile_loader silent swallow | open | — |
| 4 | Test file naming inconsistency | open | — |
| 5 | Partial-edit wizard flow test | open | — |
| 6 | New `consentement_explicite` token | accepted | — |
| 7 | `bar_or_order_number` field name | open | — |
| 8 | `AttributeError` catch documentation | open | — |
