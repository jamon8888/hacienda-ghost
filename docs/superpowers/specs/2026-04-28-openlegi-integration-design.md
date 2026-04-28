# OpenLégi Integration — Design Spec

**Date:** 2026-04-28
**Phase target:** Phase 9 (Legal Citation Verification + Federated Search)
**Status:** Design approved, ready for implementation plan

This document specifies how piighost integrates the **OpenLégi** Python client to add French legal-citation verification and federated search to the hacienda plugin. The integration is **opt-in**, configured during `/hacienda:setup`, and preserves piighost's privacy-first posture: only sanitized legal references leave the local machine.

---

## Goals

1. **Citation verification** — extract legal references from any text (LLM output, indexed doc, pasted draft) and verify each against authoritative French sources (Legifrance via OpenLégi). Detect hallucinations, renumberings (1382 → 1240), abrogated texts, fictive jurisprudence.
2. **Federated search** — one `/hacienda:search` skill that queries the user's local indexed corpus AND OpenLégi sources in parallel, with auto-annotation of legal references found in local hits.
3. **First-class CNIL access** — OpenLégi's `cnil` source becomes available to the existing RGPD subsystem (e.g., DPIA verdicts can cite CNIL decisions).
4. **Zero new heavy deps** — port OpenLégi's documented `OpenLegiClient` class into piighost (`httpx`-based, sync), no PyPI SDK to track.

## Non-goals

- Cross-jurisdiction support (EU, UK, US legal sources). French only.
- Automatic citation generation in LLM responses (out of scope; this spec is verification + search, not generation).
- Replacing piighost's local RAG. OpenLégi enriches, never replaces, the local index.
- A bundled OpenLégi MCP server. We use OpenLégi's hosted endpoint by default; users can self-host and point at it via `[openlegi].base_url`.

---

## Architecture

### One-page diagram

```
   ┌──────────────────────────────────────────────────────────────────┐
   │ Claude Desktop                                                   │
   │ ┌──────────────────────────────────────────────────────────────┐ │
   │ │ hacienda plugin (skills, markdown only)                      │ │
   │ │   /hacienda:setup           — 6-step wizard +                │ │
   │ │                              optional Step 7 (OpenLégi)      │ │
   │ │   /hacienda:legal:setup     — (re-)configure OpenLégi alone  │ │
   │ │   /hacienda:legal:verify    — 3-mode citation verifier       │ │
   │ │   /hacienda:search          — federated local + legal search │ │
   │ │   /hacienda:knowledge-base  — DEPRECATED → /hacienda:search  │ │
   │ │   (8 other existing skills unchanged)                        │ │
   │ └──────────────────────────────────────────────────────────────┘ │
   └────────────────────────────────────┬─────────────────────────────┘
                                        │ MCP stdio (FastMCP shim)
                                        ↓
   ┌──────────────────────────────────────────────────────────────────┐
   │ piighost daemon (Starlette /rpc on loopback)                     │
   │   existing 28 RPC methods                                        │
   │   + 5 NEW: extract_legal_refs, verify_legal_ref, search_legal,   │
   │            legal_passthrough, legal_credentials_set              │
   │ ┌──────────────────────────────────────────────────────────────┐ │
   │ │ NEW src/piighost/legal/ subsystem                            │ │
   │ │   PisteClient        — sync OpenLégi wrapper (httpx)         │ │
   │ │   LegalCache         — SQLite, 7d TTL refs / 5min freeform   │ │
   │ │   OutboundRedactor   — anonymize() + legal-grammar whitelist │ │
   │ │   ref_extractor      — regex parser ported from skill        │ │
   │ │   reference_models   — LegalReference, VerificationResult,   │ │
   │ │                        LegalHit (Pydantic)                   │ │
   │ │   audit_log          — every outbound call → daemon.log      │ │
   │ └──────────────────────────────────────────────────────────────┘ │
   └────────────────────────────────────┬─────────────────────────────┘
                                        │ HTTPS (only if [openlegi].enabled)
                                        ↓
                           https://mcp.openlegi.fr (or self-hosted)
```

**Network surface:** exactly one outbound endpoint, only invoked when (a) the user enabled OpenLégi during setup, (b) the cache misses, and (c) the redactor approved the payload.

**Privacy guarantee:** the only thing that leaves the local machine is sanitized legal-grammar payloads — no raw doc text, no PII tokens (besides whitelisted legal-grammar patterns), no audit-log token hashes.

---

## Daemon-side components

### New module layout

```
src/piighost/legal/
├── __init__.py
├── piste_client.py        — PisteClient class, sync httpx-based
├── cache.py               — LegalCache, SQLite at <vault>/legal_cache.sqlite
├── redactor.py            — OutboundRedactor (anonymize + legal-grammar whitelist)
├── ref_extractor.py       — regex-based extractor (ported from user's skill)
└── reference_models.py    — LegalReference, VerificationResult, LegalHit
```

### Five new MCP tools

| Tool | Network? | Cached? | Redacted? | Token req? |
|---|---|---|---|---|
| `extract_legal_refs(text: str) -> list[Reference]` | no | no | n/a | no |
| `verify_legal_ref(ref: dict) -> VerificationResult` | yes | yes (7d TTL) | yes | yes |
| `search_legal(query, source, ...) -> list[Hit]` | yes | yes (5min TTL on freeform) | yes | yes |
| `legal_passthrough(tool, args) -> dict` | yes | yes (7d TTL) | yes (force-applied) | yes |
| `legal_credentials_set(token: str) -> dict` | no | no | n/a | n/a |

`source` enum for `search_legal`: `"code" | "jurisprudence_judiciaire" | "jurisprudence_administrative" | "cnil" | "jorf" | "lois_decrets" | "conventions_collectives" | "auto"`. Auto-router dispatches by query shape (`article \d+` → code; `\d{2}-\d+\.\d+` → jurisprudence; `loi n°` → lois_decrets; etc.).

### `OutboundRedactor` — the privacy boundary

Whitelist regex set (preserved verbatim in outbound payloads):

```
\barticle\s+[LRD]?\.?\s*\d+(-\d+)*\b           # article numbers
\b(loi|décret|ordonnance)\s+n[°o]?\s*\d{2,4}-\d+ # laws
\b\d{2}-\d+\.\d+\b                             # pourvoi numbers
\b(Cass|CE|CC|CJUE)\s*[\.,]                    # court abbreviations
\b\d{1,2}\s+\w+\s+\d{4}\b                      # French dates
\bCode\s+[\w\s']+                              # code names
```

Everything outside the whitelist is sanitized via `service.anonymize()`. PII tokens (`<<nom_personne:HASH>>`) become `[REDACTED]` in the outbound payload — we don't even leak our own placeholder format. Audit event `outbound_legal_call` records: tool name, redacted payload, response hash, cache hit/miss flag.

**Failure mode:** if `OutboundRedactor` raises (anonymize crash, regex panic), the call is **refused, not retried**. We never proceed to a live OpenLégi call with un-redacted payload.

### `LegalCache` — `<vault>/legal_cache.sqlite`

```sql
CREATE TABLE legal_cache (
    cache_key   TEXT PRIMARY KEY,    -- sha256(tool || canonical_json(args))
    tool        TEXT NOT NULL,
    response    TEXT NOT NULL,       -- raw JSON from OpenLégi
    created_at  INTEGER NOT NULL,    -- epoch seconds
    ttl_seconds INTEGER NOT NULL,
    hits        INTEGER DEFAULT 0
);
CREATE INDEX idx_created ON legal_cache(created_at);
```

TTLs: 7 days for `verify_legal_ref` and `legal_passthrough` (legal references are stable), 5 minutes for freeform `search_legal` queries (avocat refines mid-research). Cache survives daemon restarts. Manual invalidation via new RPC `legal_cache_clear()`.

### `PisteClient` — sync httpx wrapper

Ported from the OpenLégi documentation example. Key differences from the docs version:
- Uses `httpx.Client` (already a base dep) not `requests`
- Strict timeout (10s connect, 30s read) — never block the daemon indefinitely
- Retries on 429 with exponential backoff + jitter, max 3 attempts
- `__enter__`/`__exit__` for explicit lifecycle (no module-level singleton)

---

## Wizard integration

### `controller.toml` extension

New optional `[openlegi]` table:

```toml
[openlegi]
enabled  = true
base_url = "https://mcp.openlegi.fr"     # or self-hosted endpoint
service  = "legifrance"                  # or "inpi", "eurlex"
# Token is NOT stored here — see credentials.toml below.
```

### Token storage — separate credentials file

`controller.toml` is profile/identity (relatively non-sensitive). PISTE tokens are credentials → separate file with stricter handling:

```
~/.piighost/credentials.toml             ← chmod 600 on POSIX, ACLs on Windows
─────────
[openlegi]
piste_token = "..."
```

The wizard creates this file with restrictive permissions. The daemon reads it on startup and on `legal_credentials_set` calls. **`controller_profile_get` strips `[openlegi]` from `credentials.toml` reads** — it only ever returns `{"openlegi": {"configured": true|false}}`. Token text never reaches an MCP response.

### Wizard Step 7 (NEW, optional)

Inserted between Step 6 (durée de conservation) and the existing "Confirm" step:

```
Step 7 — Vérification de citations juridiques (optionnel)

L'intégration OpenLégi permet de vérifier les références juridiques
(articles, lois, jurisprudences) contre les sources officielles
Legifrance + INPI + EUR-Lex. Toutes les requêtes sortantes sont
anonymisées et auditées.

Voulez-vous activer cette intégration ? (oui / non / plus_tard)

  oui      → demande le token PISTE (https://piste.gouv.fr)
             → écrit ~/.piighost/credentials.toml (chmod 600)
             → confirme avec un test ping de search_legal("test")
  non      → écrit [openlegi] enabled = false dans controller.toml
  plus_tard → skip; activable plus tard via /hacienda:legal:setup
```

### New plugin skill: `/hacienda:legal:setup`

Standalone token-collection skill the user runs anytime to enable / disable / rotate OpenLégi without rerunning the full 6-step wizard. Wraps the same `legal_credentials_set` RPC method.

### Profession defaults — no changes

The bundled `compliance/profiles/{avocat,notaire,medecin,…}.toml` files don't need updates. OpenLégi is profession-agnostic — every profession benefits from CNIL decisions when handling personal data, and code/jurisprudence access varies by profession but is universally useful.

---

## Plugin skills

### `/hacienda:legal:verify` — citation verification (3 input modes)

```
INPUT MODE DETECTION
  --doc-id <id>     → fetch doc text from indexing_store, then verify
  --project <name>  → list_documents_meta(project), verify each doc
  --file <path>     → read file via filesystem, then verify
  (no flag, with text in prompt) → verify pasted text directly

WORKFLOW (per text blob)
  1. extract_legal_refs(text)              → list[Reference]
  2. for each ref: verify_legal_ref(ref)   → VerificationResult
  3. format_report(results)                → JSON + Markdown summary
  4. (optional) render_compliance_doc(data, "verification_report")
                                           → MD/PDF in ~/.piighost/exports/
```

Output JSON shape mirrors the user's existing `legal-hallucination-checker` skill format (`metadata` / `synthese` / `details`) — any tooling that already consumes that format keeps working.

### `/hacienda:search` — federated search

```
WORKFLOW
  1. resolve_project_for_folder(<active>)               # if Cowork-aware
  2. Run query against TWO sources in parallel:
     a. local = mcp__piighost__query(text, k=10, project=<p>)
     b. legal = mcp__piighost__search_legal(text, source="auto", k=5)
        (skipped if [openlegi].enabled = false)
  3. Merge + rank with two-tier policy:
     - LOCAL hits first (the user's actual case file is most relevant)
     - LEGAL hits interleaved by relevance
     - Auto-annotation: if a LOCAL hit's text contains a regex-extractable
       legal reference, the LEGAL entry for that reference surfaces inline
       directly beneath the LOCAL hit
  4. Return list with explicit source attribution:
     [LOCAL] client_acme/contrat.pdf  p3   "...considérant l'article 1240..."
     ↳ [CODE] Code civil, Art. 1240        "Tout fait quelconque de l'homme..."
     [LEGAL] Cass. civ. 1re, 15 mars 2023, n°21-12.345  "..."
     [LOCAL] client_acme/correspondance.txt p1 "..."
```

### Existing skills

- **`/hacienda:knowledge-base`** → kept but description marked deprecated, redirects users to `/hacienda:search`. Removed in a future major plugin version.
- **`/hacienda:rgpd:dpia`** → optional enrichment: when OpenLégi is enabled, after emitting the DPIA verdict, call `search_legal(query=<verdict text>, source="cnil")` to surface relevant CNIL decisions inline. Pure UX improvement; verdict logic unchanged.
- **All 9 other skills** unchanged.

### Plugin manifest

`plugin.json` v0.7.0 → v0.8.0:
- New skills: `legal-verify`, `legal-setup`, `search`
- Deprecation marker on `knowledge-base`

### Slash command namespace

`/hacienda:legal:*` is a new namespace alongside `/hacienda:rgpd:*`. Tools in this namespace politely refuse with a setup hint when OpenLégi is disabled — they remain visible for discoverability.

---

## Error handling

| Failure mode | Behavior |
|---|---|
| `[openlegi].enabled = false` | Skill refuses with "Activez via /hacienda:legal:setup". `search_legal` returns `[]`, `verify_legal_ref` returns `VerificationResult(status="UNKNOWN_OPENLEGI_DISABLED", score=None)`. No exception bubbles to the user. |
| Missing `credentials.toml` after enable | Daemon RPC returns `{"error": "PISTE token not configured"}`. Wizard re-prompts. |
| Bad token (HTTP 401) | Cache miss → `VerificationResult(status="UNKNOWN_AUTH_FAILED")`. Audit logs the failure. Skill suggests rotating via `/hacienda:legal:setup`. |
| OpenLégi rate limit (HTTP 429) | Exponential backoff up to 3 retries with jitter. If still 429, return `UNKNOWN_RATE_LIMITED`. |
| OpenLégi unreachable (DNS / conn timeout) | After 10s timeout, return `UNKNOWN_NETWORK`. **Never** silently return "exists" for a network failure — that would be the worst possible UX for a hallucination checker. |
| OpenLégi response is malformed JSON / SSE parse failure | Same as network failure: `UNKNOWN_PARSE_ERROR` + audit entry. |
| Reference doesn't extract cleanly (regex mismatch) | `extract_legal_refs` is best-effort — returns empty list, skill warns "no references found in input" rather than failing. |
| Cache DB locked (SQLite contention on Windows) | Treat as cache miss, fall through to live call. Don't fail the verification. |
| `OutboundRedactor` crashes | **Hard fail** — refuse to send. Never proceed to a live call when redaction failed. Skill surfaces the redaction error to the avocat. |

---

## Testing strategy

### Privacy invariant — the single most important test

`tests/integration/test_legal_outbound_privacy.py`:

1. Seed vault with known PII strings (Marie Curie, IBAN, French SSN, French phone, email).
2. Build 10 input strings combining each PII string with legal references (e.g., "Marie Curie a invoqué l'article 1240 du Code civil contre Acme Corp dans Cass. civ. 1re 21-12.345").
3. Configure `OutboundRedactor` with the legal-grammar whitelist.
4. For each input, intercept the wire payload via `httpx.MockTransport`.
5. Assert NONE of the 5 known PII strings appears in any captured payload.
6. Assert the legal references DO survive (article numbers, pourvoi numbers, code names — they are whitelisted).

This is the equivalent of `test_no_pii_leak_phase2.py` for the outbound boundary.

### Testing pyramid

| Layer | What | Files |
|---|---|---|
| **Unit (pure)** | regex extractor, redactor whitelist, cache key normalization, ref classifier | `test_ref_extractor.py`, `test_outbound_redactor.py`, `test_legal_cache.py` |
| **Service** | daemon's 5 new RPC methods with `PisteClient` mocked via `httpx.MockTransport` | `test_legal_service.py` |
| **Integration** | spawn real daemon, mock OpenLégi via `httpx.MockTransport`, walk verify → search → search_legal → passthrough | `tests/integration/test_legal_e2e.py` |
| **Privacy** | the no-leak test described above | `tests/integration/test_legal_outbound_privacy.py` |
| **Live (manual, CI-skipped)** | one optional test that calls real OpenLégi with a CI-secret token, gated by `RUN_LIVE_OPENLEGI=1`. Verifies the SDK port still tracks OpenLégi's actual response shape. | `tests/live/test_legal_live.py` |

### Out of scope (deliberate)

- OpenLégi's own correctness — we treat their responses as authoritative.
- Citation classification beyond the 4 categories the user's existing skill defines (REF_INEXISTANTE / NUM_ERRONE / ABROGATION_IGNOREE / VERIFIE_EXACT). We ship the existing taxonomie.md and strategies-recherche.md as bundled references.
- Cross-jurisdiction (EU, UK, US) — explicitly out of scope. Documented in the skill description.

---

## File map

| Path | Type | Owns |
|---|---|---|
| `src/piighost/legal/__init__.py` | new | Package init + lazy `__getattr__` (PEP 562, mirrors compliance/) |
| `src/piighost/legal/piste_client.py` | new | Sync httpx wrapper — `PisteClient(token, base_url, service)` |
| `src/piighost/legal/cache.py` | new | `LegalCache(vault_dir)` SQLite-backed |
| `src/piighost/legal/redactor.py` | new | `OutboundRedactor(anonymize_fn)` |
| `src/piighost/legal/ref_extractor.py` | new | `extract_references(text) -> list[LegalReference]` (port from skill) |
| `src/piighost/legal/reference_models.py` | new | `LegalReference`, `VerificationResult`, `LegalHit` (Pydantic, `extra="forbid"`) |
| `src/piighost/legal/templates/taxonomie.md` | new (copy) | Bundled reference for the verify skill |
| `src/piighost/legal/templates/strategies-recherche.md` | new (copy) | Bundled reference for the verify skill |
| `src/piighost/service/core.py` | modify | Add 5 new `PIIGhostService.legal_*` methods |
| `src/piighost/service/config.py` | modify | New `OpenLegiSection` (enabled, base_url, service) |
| `src/piighost/service/credentials.py` | new | `CredentialsService` for `~/.piighost/credentials.toml` (chmod 600 on POSIX) |
| `src/piighost/mcp/tools.py` | modify | 5 new ToolSpec entries |
| `src/piighost/mcp/shim.py` | modify | 5 new `@mcp.tool` wrappers |
| `src/piighost/daemon/server.py` | modify | 5 new dispatch handlers |
| `pyproject.toml` | modify | Add `pytest-httpx` to test extra (no new base deps; `httpx` already there) |
| `tests/unit/test_ref_extractor.py` | new | Regex + edge cases |
| `tests/unit/test_outbound_redactor.py` | new | Whitelist + crash safety |
| `tests/unit/test_legal_cache.py` | new | TTL, invalidation, key canonicalization |
| `tests/unit/test_legal_service.py` | new | 5 RPC methods with MockTransport |
| `tests/unit/test_credentials_service.py` | new | `credentials.toml` lifecycle, get-strips-token |
| `tests/integration/test_legal_e2e.py` | new | Real daemon + mocked OpenLégi |
| `tests/integration/test_legal_outbound_privacy.py` | new | The 5-PII-strings privacy gate |
| `.worktrees/hacienda-plugin/skills/legal-verify/SKILL.md` | new | `/hacienda:legal:verify` |
| `.worktrees/hacienda-plugin/skills/legal-setup/SKILL.md` | new | `/hacienda:legal:setup` |
| `.worktrees/hacienda-plugin/skills/search/SKILL.md` | new | `/hacienda:search` |
| `.worktrees/hacienda-plugin/skills/setup/SKILL.md` | modify | Add Step 7 (optional OpenLégi enable) |
| `.worktrees/hacienda-plugin/skills/knowledge-base/SKILL.md` | modify | Mark deprecated, redirect to `/hacienda:search` |
| `.worktrees/hacienda-plugin/skills/rgpd-dpia/SKILL.md` | modify | Optional CNIL enrichment when OpenLégi enabled |
| `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` | modify | Bump v0.7.0 → v0.8.0 |

---

## Estimated effort

| Component | Effort |
|---|---|
| `piste_client.py` + tests | 2 h |
| `cache.py` + tests | 1.5 h |
| `redactor.py` + tests + privacy gate | 3 h |
| `ref_extractor.py` (port + extend) + tests | 1 h |
| `credentials.py` + tests + chmod-on-POSIX | 1.5 h |
| 5 `_ProjectService.legal_*` methods + dispatchers | 2 h |
| MCP wiring (tools.py + shim.py + server.py) | 1 h |
| `legal-verify` SKILL.md | 1 h |
| `legal-setup` SKILL.md | 30 min |
| `search` SKILL.md (federation logic) | 2 h |
| Wizard Step 7 patch | 1 h |
| Knowledge-base deprecation patch | 15 min |
| RGPD DPIA CNIL enrichment patch | 30 min |
| Integration test (real daemon + mocked OpenLégi) | 2 h |
| Documentation pass + followups doc | 1 h |
| **Total** | **~20 h (~3 days)** |

---

## Open questions deferred to plan

These are deliberately not decided in the spec — to be addressed during implementation planning:

1. Should the `auto` source router be regex-based or use a tiny classifier? (Likely regex, decide in Plan Task 4.)
2. Cache eviction policy — LRU, oldest-first, or just TTL? (Decide in Plan Task 2 based on real-world cache size.)
3. `legal_passthrough` security — does it bypass the redactor? (Spec says no; reconfirm during implementation.)
4. Should `/hacienda:search` skill ship as part of Phase 9 or a separate Phase 10? (Spec says together; flag if implementation drift suggests splitting.)
