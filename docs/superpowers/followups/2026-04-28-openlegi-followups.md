# OpenLégi (Phase 9–10) — Follow-up Issues

**Date:** 2026-04-28
**Source:** Phase 9 final review + Phase 10 closure
**Spec:** [docs/superpowers/specs/2026-04-28-openlegi-integration-design.md](../specs/2026-04-28-openlegi-integration-design.md)
**Plans:**
- [docs/superpowers/plans/2026-04-28-openlegi-integration.md](../plans/2026-04-28-openlegi-integration.md) (Phase 9)
- [docs/superpowers/plans/2026-04-28-openlegi-hardening.md](../plans/2026-04-28-openlegi-hardening.md) (Phase 10)

This file consolidates the Phase 9 final-review items: 4 fixed inline in Phase 9 (I-1 anonymizer wiring, I-2 cache key, I-4 step renumbering — done in commits `26bc086` + `cd62ab6`), and 8 deferred to Phase 10 and addressed in this round.

## Resolution log

| # | Phase 9 review | Status | Resolution |
|---|---|---|---|
| I-1 | No-op anonymize in `_legal_call` | ✅ closed | Phase 9 commit `26bc086` — pre-anonymize args via project's real anonymize before redactor |
| I-2 | Cache key uses raw args | ✅ closed | Phase 9 commit `26bc086` — cache keys now use anonymized_args |
| I-3 | 401 → UNKNOWN_NETWORK miscategorisation | ✅ closed | Phase 10 commit `7d9b957` — typed exception handlers + status_map |
| I-4 | Duplicate Step 5 headings | ✅ closed | Phase 9 plugin commit `cd62ab6` — renumbered to Step 5 + Step 6 |
| M-1 | No `legal_cache_clear` MCP tool | ✅ closed | Phase 10 commit `c5d2eaf` — new MCP tool + tests, catalog 33→34 |
| M-2 | Missing `_auto_route_source` tests | ✅ closed | Phase 10 commit `b1bfb3d` — 6 parametric cases |
| M-3 | Missing cache hit-path test | ✅ closed | Phase 10 commit `b1bfb3d` — 3-call/1-wire assertion |
| M-4 | Missing HALLUCINATION classification test | ✅ closed | Phase 10 commit `b1bfb3d` — VERIFIE_EXACT + HALLUCINATION coverage |
| M-5 | Range-form articles ("articles X à Y") | ✅ closed | Phase 10 commit `a33cacd` — new `_RE_ARTICLE_RANGE` regex |
| M-6 | Brittle `_RE_ARTICLE_CODE` terminator | ✅ closed | Phase 10 commit `a33cacd` — extended verb list + clean punctuation fallback |
| M-7 | PisteClient no retry on `RequestError` | ✅ closed | Phase 10 commit `4e64a74` — transient retries with backoff |
| M-8 | `legal_search` error vs empty | ✅ closed | Phase 10 commit `1aaec22` — `_error` source sentinel |

All 12 review items closed. The legal subsystem is production-ready for the no-ML-models path AND has live-OpenLégi smoke coverage gated behind `RUN_LIVE_OPENLEGI=1` (Phase 10 commit `c734748`).

## Test status at Phase 10 close

- **72 Phase 9+10 legal tests** pass (50 from Phase 9 + 22 from Phase 10's expansions)
- **2 live tests** skipped cleanly (no env vars set in CI)
- **89 Phase 0–8 regression** tests still green
- **Total: 161 passed + 2 skipped**

## Tool catalog growth

| Phase | Tool count |
|---|---|
| Phase 8 close | 28 |
| Phase 9 (5 legal tools) | 33 |
| Phase 10 (`legal_cache_clear`) | **34** |

## New follow-ups surfaced during Phase 10 (none → 🟢 nice-to-have only)

No new architectural concerns. Three minor v1.2 candidates:

### 🟢 1. `_error` source sentinel is convention-only

`legal_search` returns `[{"source": "_error", ...}]` on errors, but `LegalHit.source` is typed as `Literal["code", "jurisprudence_judiciaire", ...]` — `_error` isn't in that union. Currently it works because Pydantic doesn't re-validate dict outputs at the MCP boundary; if a future refactor calls `LegalHit.model_validate(...)` on returned dicts, the sentinel would fail validation.

**Fix:** add `"_error"` to the `Literal` union in `reference_models.py:LegalHit.source`, OR define a separate `LegalError` Pydantic model and have `legal_search` return `list[LegalHit] | list[LegalError]` (typed). Defer until a refactor needs it.

### 🟢 2. `legal_cache_clear` operates on the daemon-wide cache

One SQLite under `~/.piighost/legal_cache.sqlite` — there's no per-project scoping. If a future requirement calls for per-project caches (e.g., separate caches per Cowork folder), `legal_cache_clear` needs a `project: str | None` parameter and `LegalCache(vault_dir=...)` would need to take the per-project vault dir.

**Fix path:** when the per-project requirement surfaces, add the optional `project` parameter to both the service method and the MCP tool description. Backward-compatible (no arg = clear global).

### 🟢 3. Live tests don't assert exact response shape

`tests/integration/test_legal_live.py` only asserts "real hits returned" + "VERIFIE_EXACT" — not the SSE format or the JSON-RPC envelope. If OpenLégi changes their SSE format or wraps their response in extra layers, the live tests pass but `_parse_sse` silently degrades and our verification gets noisy.

**Fix:** add a "schema drift detector" that asserts the captured response has the exact keys we expect (`{"jsonrpc": "2.0", "id": int, "result": {"hits": [...]}}`). If OpenLégi adds a wrapping layer or renames fields, the test fails loudly.

Track for v1.2 — only matters if OpenLégi is changing their endpoint shape, which they currently aren't (verified against their docs as of 2026-04-28).
