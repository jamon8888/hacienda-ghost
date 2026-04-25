# Forward HTTPS proxy for Claude Desktop interception

**Date:** 2026-04-25
**Status:** Draft (awaiting approval)
**Owners:** piighost maintainers
**Supersedes (partially):** strict-mode hosts-file approach in `2026-04-24-anonymizing-proxy-cross-host.md` for Claude Desktop specifically. Light mode (`ANTHROPIC_BASE_URL`) for Claude Code is unchanged.

## 1. Problem

Strict mode (hosts-file redirect + trusted CA + leaf cert for `api.anthropic.com`) was implemented in phase 2 to intercept clients that don't honor `ANTHROPIC_BASE_URL`. Claude Desktop is the primary such client.

In practice, strict mode is bypassed by Claude Desktop. The proxy receives no traffic when Desktop sends a message. Root cause is one or more of:

- **DoH (DNS-over-HTTPS):** Chromium-based Electron apps perform DNS over HTTPS to public resolvers (`1.1.1.1`, `8.8.8.8`), bypassing the OS resolver and therefore the hosts file.
- **Chromium internal resolver:** Chromium's net stack maintains its own host cache and can ignore `/etc/hosts` for hostnames it has previously resolved.
- **(Possibly) cert pinning:** TLS handshake reaches the proxy but Desktop rejects the leaf cert. Reports suggest Desktop does NOT pin, but we treat this as a probe-confirmed assumption rather than a guarantee.

The downstream consequence: Claude Desktop sends user PII straight to `api.anthropic.com` with zero anonymization, defeating piighost's core promise.

## 2. Goal

Intercept and anonymize **every** API request Claude Desktop makes to Anthropic — chat messages, document uploads, batch requests, tool inputs and tool results — with a deterministic guarantee that no PII reaches Anthropic when piighost is functioning, and a fail-closed behavior (Desktop cannot reach Anthropic at all) when it isn't.

Coverage target:

| Endpoint / payload | Goal |
|---|---|
| `POST /v1/messages` text content blocks | anonymize all text fields |
| `POST /v1/messages` `tool_use.input` (JSON) | anonymize string values inside the structured input |
| `POST /v1/messages` `tool_result.content` | anonymize text; recurse into nested content blocks |
| `POST /v1/messages` `image` content blocks | pass through unchanged (see warning below) |
| `POST /v1/messages` `document` content blocks (base64) | extract text, anonymize, repackage. Formats: PDF, DOCX, XLSX, PPTX, ODT, ODS, TXT (delegated to existing `indexer/ingestor.py:extract_text()`) |
| `POST /v1/messages` `document` content blocks by `file_id` reference | resolve the file_id to its prior anonymization mapping (see §6.5); no re-extraction needed |
| `POST /v1/files` uploads | extract text via existing extractor, anonymize, re-upload anonymized bytes; persist `file_id → mapping` binding to the vault |
| `POST /v1/messages/batches` | anonymize each request in the batch using the same handlers above |
| Streaming SSE responses | rehydrate placeholders in `text_delta`, `input_json_delta`, and tool_result content back to original PII |
| Any unknown Anthropic endpoint | **block** (fail-closed; do not pass through) |

> ⚠️ **Image and screenshot caveat — known coverage gap.**
> Image content blocks pass through the proxy unchanged. If a user attaches a screenshot, scanned ID, or photographed document containing PII, that PII reaches Anthropic. This applies equally to Computer Use screenshots returned in `tool_result`. v1 does not OCR or anonymize image bytes. Surfaced in the install summary, the doctor output, and the system-tray banner so the user is informed.

> ℹ️ **MCP server traffic is out of scope.**
> Claude Desktop's configured MCP servers run as local processes; their traffic does not reach `api.anthropic.com` and is not affected by this proxy. Anonymization at the MCP boundary is a separate concern handled by the existing piighost MCP server (`src/piighost/mcp/`).

## 3. Non-goals

- Replacing the existing `light` mode for Claude Code or SDK clients that honor `ANTHROPIC_BASE_URL`. That path stays as-is.
- Image/audio content inspection or OCR. v2 candidate.
- Defeating true public-key pinning if Desktop ever introduces it. The diagnostic command will detect pinning and surface a clear failure.
- Anonymizing model-generated text (the model's output is rehydrated, not anonymized).
- Generic system-wide HTTPS interception. Scope is per-process, Claude Desktop only.
- MCP server interception (see §2). MCP traffic is local and does not transit `api.anthropic.com`.

## 4. Architecture

```
┌──────────────────┐      ┌────────────────────────────────────────────┐      ┌──────────────────┐
│ Claude Desktop   │      │  piighost forward proxy (mitmproxy core)   │      │ api.anthropic.com│
│ (Electron)       │      │ ┌──────────┐  ┌─────────┐  ┌─────────────┐ │      │                  │
│  launched via    │─CONN─▶│ │ CONNECT  │─▶│  Leaf   │─▶│ HTTP req    │─▶ TLS▶│                  │
│  piighost shim   │      │ │  handler │  │  cert   │  │ dispatcher  │ │      │                  │
│                  │◀TLS──│ │ (mitm)   │  │ minter  │  │  (per       │ │◀SSE──│                  │
│ HTTPS_PROXY      │      │ └──────────┘  └─────────┘  │  endpoint)  │ │      │                  │
│ = 127.0.0.1:8443 │      │                            └──────┬──────┘ │      │                  │
│ NODE_EXTRA_      │      │                                   ▼        │      │                  │
│  CA_CERTS=...    │      │            ┌─────────────────────────────┐ │      │                  │
│                  │      │            │ piighost addon              │ │      │                  │
│ trusts piighost  │      │            │  - /v1/messages anonymizer  │ │      │                  │
│ CA via Windows   │      │            │  - /v1/files anonymizer     │ │      │                  │
│ trust store      │      │            │  - /v1/batches anonymizer   │ │      │                  │
└──────────────────┘      │            │  - SSE rehydrator           │ │      │                  │
                          │            │  - unknown endpoint blocker │ │      │                  │
                          │            └─────────────────────────────┘ │      │                  │
                          │  non-Anthropic CONNECT → raw tunnel        │      │                  │
                          └────────────────────────────────────────────┘      └──────────────────┘
```

**Why this defeats the diagnosed bypass:**
Claude Desktop never resolves `api.anthropic.com` itself. It sends `CONNECT api.anthropic.com:443 HTTP/1.1` over a plain TCP connection to `127.0.0.1:8443`. Name resolution becomes the proxy's job. DoH, Chromium internal resolver, and direct-IP shortcuts are bypassed by construction.

**Why mitmproxy is the engine:**
CONNECT parsing, dynamic per-host leaf-cert minting, ALPN negotiation, HTTP/2 over TLS, SSE chunking, and WebSocket upgrades are all solved problems in mitmproxy. The piighost rewrite logic becomes a `~150-line` mitmproxy addon. The existing detection pipeline (`AnonymizationPipeline`, `Anonymizer`, `vault`) is reused unchanged.

**Why per-process scope (not system-wide proxy):**
A bug in piighost should break Claude Desktop only, not every HTTPS-using app on the machine. Per-process scope is achieved by launching Desktop through a wrapper that injects `HTTPS_PROXY` and `NODE_EXTRA_CA_CERTS` into its environment. This is the same pattern corporate EDR/DLP/VPN clients use.

## 5. Components

### 5.1 New components

#### `src/piighost/proxy/forward/` — mitmproxy-based forward proxy

A new submodule, separate from the existing `src/piighost/proxy/` Starlette app (which stays for `light` mode and direct API use).

| File | Responsibility |
|---|---|
| `__main__.py` | Entry point for `piighost proxy run --mode=forward` — boots mitmproxy with the piighost addon and the existing CA. |
| `addon.py` | mitmproxy addon class. Implements `request()` and `response()` hooks. Routes by URL to the per-endpoint handlers. |
| `dispatch.py` | Endpoint dispatcher. Maps `(method, path)` → handler. Unknown Anthropic paths return a `403` to the client. |
| `handlers/messages.py` | Anonymize `POST /v1/messages` body — text blocks, `tool_use.input` (JSON), `tool_result.content` (recursive). Rehydrate SSE response. Wraps existing `rewrite_request_body` / `rewrite_sse_stream`. |
| `handlers/tool_blocks.py` | Recursive anonymizer for nested tool_use/tool_result schemas. JSON-aware: walks the structure, anonymizes string leaves only, preserves keys and types. |
| `handlers/files.py` | Anonymize `POST /v1/files` multipart upload. Delegates extraction to existing `indexer/ingestor.py:extract_text()`. After upload succeeds, persists `file_id → mapping` binding to vault (see §6.5). |
| `handlers/batches.py` | Anonymize each request inside `POST /v1/messages/batches`. Reuses `messages.py` handler per item. |
| `handlers/documents.py` | Document content block dispatcher. For inline base64: delegates extraction to existing `indexer/ingestor.py:extract_text()`. For `file_id` references: resolves via `vault.file_bindings.lookup(file_id)`. |
| `handlers/unknown.py` | Default fail-closed handler: returns `403` with audit-logged "endpoint not in piighost coverage matrix". |

#### `src/piighost/install/desktop_wrapper/` — Claude Desktop launch shim

| File | Responsibility |
|---|---|
| `wrapper.py` | The shim itself. Sets `HTTPS_PROXY`, `NODE_EXTRA_CA_CERTS`, and Windows Firewall rules; execs the real Claude Desktop binary. Compiled to `piighost-claude-desktop.exe` via PyInstaller. |
| `shortcut.py` | Replaces Start Menu / Desktop / pinned-taskbar shortcuts to point at the wrapper. |
| `update_watch.py` | Scheduled task body. Watches Claude Desktop install dir for version changes; re-runs `shortcut.py` after updates. |
| `firewall.py` | Adds/removes per-process Windows Firewall rules blocking direct outbound to `*.anthropic.com:443` for `Claude.exe`. |

#### `src/piighost/cli/doctor.py` (new flag)

`piighost doctor --diagnose-desktop` — runs a canary message through Claude Desktop, asserts the canary appears anonymized in the audit log, and asserts the response is correctly rehydrated. Includes pinning probe (presents both a wrong-CN and right-CN leaf cert, observes Desktop's reaction).

### 5.2 Reused (unchanged)

- `src/piighost/anonymizer.py` — anonymization core
- `src/piighost/pipeline/` — detection / linking / resolution pipeline (including `ThreadAnonymizationPipeline` for cross-message linking)
- `src/piighost/indexer/ingestor.py` — `extract_text(path)` via kreuzberg. Handles PDF, DOCX, XLSX, PPTX, ODT, ODS, TXT. **The forward proxy MUST reuse this function**; it must not introduce a parallel extractor.
- `src/piighost/indexer/chunker.py` — used when an extracted document is too large for a single anonymization pass.
- `src/piighost/vault/` — project-scoped storage. Extended with a new `file_bindings` table (see §6.5).
- `src/piighost/proxy/upstream.py` — `AnthropicUpstream` HTTP client (used by mitmproxy addon for upstream calls when needed; mitmproxy's own upstream connection is the default path)
- `src/piighost/proxy/audit.py` — audit log writer
- `src/piighost/install/ca.py` — CA generation. Leaf cert minting moves to mitmproxy's built-in (which uses our CA).
- `src/piighost/install/trust_store/` — OS trust store install (already deploys CA to `LocalMachine\Trusted Root` on Windows)

### 5.3 Removed / deprecated

- `src/piighost/install/hosts_file.py` — no longer needed for Claude Desktop. Stays for any future client that requires hosts-based redirect; deprecation noted in CLI help.
- The `--mode=strict` install flag is renamed to `--mode=hosts` (legacy) and a new `--mode=forward` is added as the default for Desktop-class clients.

## 6. Data flow

### 6.1 Outbound message (Claude Desktop → Anthropic)

1. User sends a message in Claude Desktop. Desktop's Chromium net stack sees `HTTPS_PROXY=127.0.0.1:8443` in its environment (set by wrapper) and routes the request through it.
2. Desktop opens TCP to `127.0.0.1:8443` and sends `CONNECT api.anthropic.com:443 HTTP/1.1`.
3. mitmproxy responds `200 Connection Established`. It dynamically mints a leaf cert for `api.anthropic.com` signed by piighost CA (cached after first mint).
4. Desktop performs TLS handshake against the leaf cert. Trust store install means Windows trusts the chain. Handshake succeeds.
5. Desktop sends `POST /v1/messages` (or `/v1/files`, etc.) over the now-decrypted tunnel.
6. mitmproxy's `request()` hook fires the piighost addon. The dispatcher routes to the matching handler.
7. The handler walks the message structure and anonymizes:
   - `messages[].content[]` text blocks → `AnonymizationPipeline.anonymize(text, thread_id=...)`
   - `messages[].content[]` `tool_use.input` → recursive JSON walk via `handlers/tool_blocks.py`; anonymizes string leaves only, preserves keys and types
   - `messages[].content[]` `tool_result.content` → recurses into nested blocks (text or further structured content)
   - `messages[].content[]` `document` blocks → extract via `indexer/ingestor.py:extract_text()`, anonymize, repackage as base64
   - `messages[].content[]` `document` blocks referencing `file_id` → load the binding from `vault.file_bindings`, ensure the mapping is in the thread context (no re-extraction)
   - `system` field → text anonymization
8. Mappings are written to the project vault, scoped by `project + thread_id`. Optionally promoted to the project-wide `entity_index` if `--enable-vault-enrichment` is on (§7b).
9. mitmproxy forwards the anonymized request to the real `api.anthropic.com:443` over its own outbound TLS connection.

### 6.2 Inbound response (Anthropic → Claude Desktop)

1. Anthropic streams an SSE response.
2. mitmproxy's `response()` hook fires the piighost addon's SSE rehydrator. Per chunk type:
   - `content_block_delta` with `text_delta` → placeholder substitution in the text payload
   - `content_block_delta` with `input_json_delta` → buffered per `content_block_index` until the JSON is parseable, then walked recursively to substitute placeholders in string leaves
   - `content_block_start` for a `tool_use` block → no rehydration needed (input arrives via deltas)
   - `content_block_start` for a `tool_result` block (server-sent) → recurse into content blocks
   - `message_delta` / `message_stop` / `ping` → forwarded unchanged
3. Substitution uses cache-first lookup (mapping written at request time), with entity-based fallback (re-detect placeholders, look up entity-level mapping) for cases where the cache was evicted.
4. mitmproxy sends the rehydrated stream to Claude Desktop over the original tunnel.
5. User sees the model's response with their real names, addresses, etc. — never the placeholders.

### 6.3 Unknown endpoint

1. Desktop calls an Anthropic endpoint piighost doesn't know about (e.g., a future `POST /v1/whatever`).
2. Dispatcher routes to `handlers/unknown.py`.
3. Handler returns HTTP `403` with body `{"error":"piighost: endpoint not in coverage matrix; update piighost or contact support"}` and writes an audit record.
4. Desktop surfaces the error to the user. **No request reaches Anthropic.**

This is the fail-closed core of the design. Adding new endpoints to the coverage matrix becomes a deliberate, reviewable code change — never an accidental passthrough.

### 6.4 Non-Anthropic CONNECT (e.g., telemetry, update check)

1. Desktop sends `CONNECT updates.anthropic.com:443` or any other non-API host.
2. mitmproxy's CONNECT handler checks against piighost's "intercept allowlist" (only `api.anthropic.com`).
3. Non-allowlisted hosts get a raw TCP tunnel — mitmproxy does NOT terminate TLS. Bytes flow through unmodified.
4. This means non-API Anthropic hosts (telemetry, updates) work normally with no piighost involvement and no decryption.

### 6.4b Thread and project resolution

Claude Desktop does not send a `thread_id` field in API requests. The proxy must derive one for placeholder linking across messages in the same conversation. Resolution order:

1. **`metadata.user_id`** — if Desktop populates this (it does for some accounts), use it as the thread key. Stable per Desktop install.
2. **Conversation-state header** — Desktop includes `anthropic-conversation-id` (or equivalent, TBD on inspection of real traffic in §10.3 manual testing) in some flows. Captured if present.
3. **Hash of the first user message in `messages[]`** — if no other identifier exists, hash the first message's content. Same conversation → same hash → same thread. New conversation → new hash → new thread.
4. **Fallback**: `"claude-desktop-default"`. This loses cross-message linking but never blocks the request.

The active **project** is derived from the active piighost project (`service.active_project()`), set via `piighost projects use <name>`. Switching project mid-session causes the wrapper to surface a tray notification — placeholder mappings are project-scoped and a switch effectively starts a new isolation boundary.

### 6.5 File-ID lifecycle (Files API)

The Anthropic Files API decouples upload from message use:

```
Upload:    Client → POST /v1/files (bytes) → returns {"id": "file_abc123"}
Reference: Client → POST /v1/messages with content block:
             {"type": "document", "source": {"type": "file", "file_id": "file_abc123"}}
```

The proxy must keep the anonymization mapping coherent across this two-step flow. New table in the project vault:

```sql
CREATE TABLE file_bindings (
    file_id        TEXT PRIMARY KEY,           -- Anthropic file_id
    project        TEXT NOT NULL,              -- piighost project scope
    thread_id      TEXT NOT NULL,              -- conversation thread for placeholder reuse
    mapping_blob   BLOB NOT NULL,              -- serialized anonymization mapping (entity → placeholder)
    original_sha256 TEXT NOT NULL,             -- detect re-upload of identical content
    anonymized_sha256 TEXT NOT NULL,           -- what Anthropic actually has
    uploaded_at    INTEGER NOT NULL,           -- unix epoch
    expires_at     INTEGER NOT NULL,           -- TTL: 90 days, matches Anthropic file retention
    UNIQUE(project, original_sha256)           -- dedupe re-uploads of same content
);
CREATE INDEX idx_file_bindings_project ON file_bindings(project);
CREATE INDEX idx_file_bindings_expires ON file_bindings(expires_at);
```

Lifecycle rules:

1. **Upload (`POST /v1/files`)**: handler extracts text, anonymizes against the active project + thread, uploads anonymized bytes, captures the returned `file_id`, writes a `file_bindings` row.
2. **Reference (`POST /v1/messages` with `file_id`)**: handler does NOT need to re-anonymize the file (already done at upload). It looks up the binding to ensure the mapping is loaded into the thread context — so when Anthropic's response quotes content from the file, the rehydrator can reverse-map placeholders back to original PII.
3. **Re-upload of identical content**: dedupe via `original_sha256` lookup; reuse existing `file_id` rather than creating duplicate Anthropic uploads.
4. **Expiry**: Anthropic retains files for ~90 days. A daemon-side janitor sweeps `file_bindings` where `expires_at < now()`, dropping stale rows and the corresponding mapping data.
5. **Delete (`DELETE /v1/files/{id}`)**: handler forwards delete to Anthropic and removes the `file_bindings` row.
6. **Cross-project isolation**: a `file_id` belongs to exactly one project. Attempting to reference it from a different project's session returns `403`.

## 7. Endpoint coverage matrix and fail-closed dispatch

The dispatcher table is the single source of truth for what piighost will and won't pass through. It lives in `src/piighost/proxy/forward/dispatch.py`:

```python
COVERAGE_MATRIX: dict[tuple[str, str], Handler] = {
    ("POST", "/v1/messages"): MessagesHandler(),
    ("POST", "/v1/messages/batches"): BatchesHandler(),
    ("GET",  "/v1/messages/batches/{id}"): BatchesGetHandler(),
    ("POST", "/v1/files"): FilesHandler(),
    ("GET",  "/v1/files/{id}"): FilesGetHandler(),  # metadata, no PII
    ("DELETE", "/v1/files/{id}"): FilesDeleteHandler(),
    ("GET",  "/v1/models"): PassthroughHandler(),  # no PII
    ("GET",  "/v1/models/{id}"): PassthroughHandler(),
}
DEFAULT_HANDLER = UnknownEndpointHandler()  # returns 403, audit-logged
```

- New Anthropic endpoints not in the table are **rejected** until explicitly added.
- A passing CI test asserts the matrix is non-empty and contains all currently-public Anthropic endpoints (test sourced from a lightly-maintained list in the test suite).
- `piighost doctor --list-coverage` prints the matrix.

## 7b. Optional vault-aware enrichment

Piighost's vault already indexes the user's project content via `indexer/embedder.py`, with a `retriever` that supports BM25 + vector + cross-encoder rerank. The forward proxy can leverage this to make placeholder assignment **stable across sessions**:

1. **At anonymization time**, after the detection pipeline produces an entity, the anonymizer queries `vault.entity_index` for that entity's canonical placeholder (if any).
2. If a canonical placeholder exists, reuse it. Otherwise mint a new one and write it back to the index.
3. Net effect: "Patrick Dupont" gets `<<PERSON_42>>` today, tomorrow, and next month — across conversations, file uploads, and re-indexed documents.

Behavior flag: `--enable-vault-enrichment` in `piighost proxy run`, default **on**. Disabling falls back to per-thread mappings only (current behavior).

Trade-off: stable placeholders can be **fingerprintable** if a user shares conversations with Anthropic support and Anthropic correlates `<<PERSON_42>>` across multiple threads. Documented in privacy notes; per-project salt mitigates by varying placeholders between projects.

## 8. Install / deployment

### 8.1 Per-developer install (single command)

```bash
piighost install --mode=forward --client=claude-desktop
```

Performs (idempotently):

1. Generate CA if not present (`install/ca.py`).
2. Install CA to `LocalMachine\Trusted Root Certification Authorities` (existing `install/trust_store/windows.py`).
3. Install `piighost-claude-desktop.exe` wrapper into `%LOCALAPPDATA%\piighost\bin\`.
4. Locate Claude Desktop install (registry: `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude*`).
5. Replace Start Menu shortcut, Desktop shortcut, and pinned-taskbar entry to point at wrapper. Original target stored for uninstall.
6. Add Windows Firewall rule blocking outbound to `*.anthropic.com:443` for the original `Claude.exe`. (Wrapper unsets this rule for itself by injecting traffic to the proxy first.)
7. Register a scheduled task `piighost-desktop-watch` (runs every 5 minutes) that re-shims after any Claude Desktop update.
8. Run `piighost doctor --diagnose-desktop`. If diagnostic fails, install is rolled back.

### 8.2 Enterprise rollout (Intune / GPO)

Same artifacts, deployed via Intune as:

- **`piighost-msi`** — packages CA, wrapper binary, and post-install hook. Deploys to `%LOCALAPPDATA%\piighost\` per-user (no admin needed for the bin).
- **GPO Computer Configuration → Public Key Policies → Trusted Root** — pushes the piighost CA to all machines. (Admin-side action, one-time.)
- **Intune script** — runs `piighost install --mode=forward --client=claude-desktop --silent` post-install.
- **Intune compliance check** — runs `piighost doctor --diagnose-desktop --quiet --json` weekly. Non-zero exit triggers a remediation script that re-runs install.

### 8.3 Uninstall

```bash
piighost uninstall --client=claude-desktop
```

Restores original shortcuts, removes wrapper, removes firewall rule, removes scheduled task. CA stays unless `--purge-ca` is passed.

## 9. Error handling and fail-closed behavior

### 9.1 Proxy down

- Wrapper checks proxy health (`GET /piighost-probe` on `127.0.0.1:8443`) before launching Desktop.
- If proxy is down: wrapper prompts user with three choices (logged in audit):
  - **Start proxy** (default) — wrapper runs `piighost daemon start`, retries probe.
  - **Open Desktop in offline mode** — wrapper exits without launching Desktop. Desktop alone is fine; no API calls happen.
  - **Emergency bypass** — wrapper launches Desktop without proxy, but with a system-tray banner and audit-log entry. Disabled by default; requires `--allow-bypass` flag at install time.

### 9.2 Proxy crashes mid-session

- Desktop's HTTPS connection drops; Desktop shows a network error.
- Self-healing daemon (already implemented in commit `21a8a19`) restarts the proxy.
- User retries the message. No data leaks because the firewall rule still blocks direct connection to Anthropic.

### 9.3 Detection pipeline error

- Anonymization fails for a specific message (e.g., GLiNER2 OOM).
- Handler returns HTTP `503` to Desktop. Desktop shows "service unavailable, try again." **The unanonymized request never reaches Anthropic.**

### 9.4 Cert pinning detected

- `piighost doctor --diagnose-desktop` runs a pinning probe at install time.
- If pinning is detected, install fails with a clear message: "Claude Desktop version X.Y.Z appears to pin Anthropic's certificate. Approach 1 cannot intercept this version. File issue."
- This converts a silent failure into a loud one before users rely on broken interception.

### 9.5 Claude Desktop auto-update

- The 5-minute scheduled task detects version change.
- Re-runs `shortcut.py` to re-shim the (potentially regenerated) shortcuts.
- Re-runs `firewall.py` to re-apply the per-`Claude.exe` block (executable path may have changed).
- Re-runs `piighost doctor --diagnose-desktop`. On failure, system tray notifies user.

## 10. Testing strategy

### 10.1 Unit tests

- `tests/proxy/forward/test_dispatch.py` — coverage matrix routing, unknown endpoint rejection.
- `tests/proxy/forward/test_handlers_messages.py` — `/v1/messages` anonymize/rehydrate round-trip; covers text, tool_use.input, tool_result.content.
- `tests/proxy/forward/test_handlers_tool_blocks.py` — recursive JSON walk; preserves keys/types, anonymizes string leaves.
- `tests/proxy/forward/test_handlers_files.py` — multipart PDF/DOCX/XLSX upload anonymization; verifies reuse of `indexer/ingestor.py:extract_text()` (no parallel extractor).
- `tests/proxy/forward/test_handlers_documents.py` — base64 inline document extract+anonymize+repackage; file_id reference resolution via `vault.file_bindings`.
- `tests/proxy/forward/test_handlers_batches.py` — batch request anonymization.
- `tests/proxy/forward/test_handlers_unknown.py` — fail-closed 403 + audit record.
- `tests/proxy/forward/test_file_bindings.py` — vault binding CRUD; dedupe via `original_sha256`; expiry sweep; cross-project isolation 403.
- `tests/proxy/forward/test_vault_enrichment.py` — placeholder stability across threads when `--enable-vault-enrichment` is on; per-project salt isolation.
- `tests/install/test_desktop_wrapper.py` — shortcut replace/restore, firewall rule lifecycle.

### 10.2 Integration tests

- `tests/integration/test_forward_proxy_e2e.py` — runs mitmproxy with the addon against a fake Anthropic upstream, hits it via a Playwright-controlled headless Chromium configured with `HTTPS_PROXY=127.0.0.1:<port>`, asserts:
  - `CONNECT` is honored
  - Leaf cert chain validates
  - SSE round-trip preserves user-original PII end-to-end
  - Unknown endpoint returns 403
- Skipped on Windows CI (model loading) — runs in WSL Ubuntu (per repo convention, see [feedback_wsl_tests.md](file:///C:/Users/NMarchitecte/.claude/projects/C--Users-NMarchitecte-Documents-opencode-hacienda/memory/feedback_wsl_tests.md)).

### 10.3 Manual / staging

- `piighost doctor --diagnose-desktop` — automated canary against a real Claude Desktop install. Ships as a built-in command.
- Documented "smoke-test checklist" in `docs/manual-testing/forward-proxy.md` for QA before release.

## 11. Migration

- Existing `light` mode users (Claude Code with `ANTHROPIC_BASE_URL`) are unaffected. No behavior change.
- Existing `strict` mode users (hosts-file) are migrated:
  - On `piighost self-update`, post-install hook detects `strict` install, prints a migration notice and the recommended command: `piighost install --mode=forward --client=claude-desktop --migrate-from-strict`.
  - The `--migrate-from-strict` flag is a new addition: it removes the hosts-file sentinel block and any prior `strict` artifacts before running the forward-mode install.
  - Hosts-file mode stays available behind `--mode=hosts` (renamed from `strict`) for users who explicitly need it.
- Vault schema migration:
  - New `file_bindings` table (§6.5) — additive, no data migration needed. Created on first run of forward-mode proxy.
  - New `entity_index` table (§7b, only if `--enable-vault-enrichment` is on) — additive. Backfilled lazily as new entities are detected; no upfront migration.

## 12. Open questions / risks

- **Mitmproxy Windows packaging**: mitmproxy depends on `cryptography` and other native deps. We need to confirm these freeze cleanly into the existing piighost PyInstaller bundle. Risk: bundle size grows ~30 MB. Mitigation: lazy-load mitmproxy only when `--mode=forward` is used.
- **Per-`Claude.exe` Windows Firewall rule**: requires the executable path to be stable. Auto-update may relocate `Claude.exe`. Mitigation: scheduled task re-applies rule on update.
- **Windows admin requirement for trust store install**: `LocalMachine\Trusted Root` requires admin. For non-admin users, fall back to `CurrentUser\Trusted Root` — Electron's net stack reads both. Documented; tested.
- **Mitmproxy upstream cert validation**: by default mitmproxy validates upstream certs, which is what we want for `api.anthropic.com`. We must ensure no `--ssl-insecure` flag leaks into the production config.

## 13. Acceptance criteria

The design is implemented when:

- [ ] `piighost install --mode=forward --client=claude-desktop` succeeds end-to-end on a fresh Windows 10/11 VM with Claude Desktop installed.
- [ ] `piighost doctor --diagnose-desktop` passes: a canary message sent through Claude Desktop appears anonymized in the upstream-bound request body and rehydrated correctly in the rendered response.
- [ ] Killing the piighost proxy mid-session prevents Claude Desktop from reaching `api.anthropic.com` (firewall rule confirmed by `Test-NetConnection api.anthropic.com -Port 443` from inside Claude Desktop's process via PsExec).
- [ ] Sending a request to `POST /v1/wat` (an unknown endpoint) from inside Desktop receives `403` and an audit record exists.
- [ ] After a Claude Desktop auto-update, the shortcut and firewall rule are re-applied within 5 minutes (scheduled task verified).
- [ ] Document upload (PDF with synthetic PII) via Desktop's attach-file UI results in an anonymized upload to `/v1/files`, verified by inspecting the upstream-bound payload in mitmproxy's flow log.
- [ ] After uploading a file, sending a message that references it by `file_id` produces a coherent response: placeholders in the model's quote of the file are rehydrated to the user's original PII.
- [ ] Re-uploading identical content (same `original_sha256`) reuses the existing `file_id` rather than creating a duplicate Anthropic upload.
- [ ] Tool-use round-trip: a message that triggers a tool with PII-containing input has the input anonymized in the upstream-bound request; the model's text response that quotes the tool result is rehydrated correctly.
- [ ] A multi-format extraction smoke test: uploading PDF, DOCX, XLSX, PPTX, ODT, ODS, TXT each produce anonymized upstream payloads. Failure to extract any format does NOT silently pass through the original — it returns 503.
- [ ] With `--enable-vault-enrichment` on, the same entity ("Patrick Dupont") gets the same placeholder across two distinct conversation threads in the same project.
- [ ] All unit tests pass on Windows; integration tests pass on WSL.
- [ ] `piighost uninstall --client=claude-desktop` fully restores the system.
