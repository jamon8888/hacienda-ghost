# Anonymizing HTTPS proxy: cross-host PII enforcement

**Date:** 2026-04-24
**Status:** Draft (awaiting approval)
**Owners:** piighost maintainers

## 1. Problem

Regulated European professionals (avocats, notaires, médecins, DPO) use Anthropic hosts — Claude Code, Claude Desktop, Cowork — to work on client files containing PII. Today's protection relies on prose: the hacienda Cowork plugin's skills *instruct* the model to call `anonymize_text` before responding. This is cooperative, not enforced. By the time a skill fires, the user's raw prompt is already in the model's context, which is already in flight to `api.anthropic.com`.

We need a deterministic enforcement layer that guarantees no raw PII leaves the user's machine, regardless of which host they use.

## 2. Non-goals

- Replacing the existing MCP server or plugin (`src/piighost/mcp/`, `plugin/`). They stay.
- Anonymizing content inside images, audio, or other non-text blocks. v1 passes non-text through unchanged with a warning.
- Intercepting non-`/v1/messages` Anthropic endpoints (`/v1/files`, `/v1/batches`, legacy `/v1/complete`). Pass-through in v1.
- Blocking the model from hallucinating new PII-like strings. The proxy redacts what the *user* provided, not what the model invents.
- Adding kernel-level network filtering (eBPF, WFP, PF). Too invasive for a desktop tool.

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Hosts: Claude Code · Claude Desktop · Cowork · SDK clients  │
│  All resolve api.anthropic.com → 127.0.0.1:443 via hosts     │
│  file (strict mode), or honor ANTHROPIC_BASE_URL (light mode)│
└────────────────────────┬─────────────────────────────────────┘
                         │  HTTPS (local CA trusted by OS)
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │  piighost-proxy   (src/piighost/proxy/)                  │
  │                                                          │
  │   ① parse Anthropic /v1/messages request body            │
  │   ② anonymize messages[].content, tool_result, system,   │
  │      tool_use.input via AnonymizationPipeline            │
  │      (project-scoped, vault-backed)                      │
  │   ③ forward to real api.anthropic.com via httpx          │
  │   ④ stream SSE response back to host                     │
  │   ⑤ rehydrate text_delta and input_json_delta chunks     │
  │      (tail-buffered for split placeholders)              │
  │   ⑥ write audit record (~/.piighost/audit/)              │
  └────────────────────────┬─────────────────────────────────┘
                           │
                           ▼
                  api.anthropic.com (sees placeholders only)

  Unchanged, parallel:
  ┌──────────────────────────────────────────────────────────┐
  │  MCP server (src/piighost/mcp/) — stdio, FastMCP          │
  │  Daemon (src/piighost/daemon/) — JSON-RPC, loopback HTTP  │
  │  Vault + pipeline — shared with proxy                     │
  └──────────────────────────────────────────────────────────┘
```

### 3.1 Invariants

1. Nothing leaves the machine toward `api.anthropic.com` without passing through the proxy (strict mode) or, for Claude Code CLI, through a proxy-pointed `ANTHROPIC_BASE_URL` (light mode).
2. The proxy's anonymization is **fail-closed**: any error in detection, vault write, or forwarding aborts the request. No raw pass-through, ever.
3. Project/thread scoping is pinned per session. The proxy resolves the active project once per incoming connection from `~/.piighost/active-project` — a small state file written by `piighost project use <name>` (explicit) or by host plugin hooks when the user opens a folder (implicit, best-effort).
4. Placeholder stability is guaranteed by the existing `Vault` / `ProjectRegistry` — the same entity in the same project maps to the same placeholder across turns, so Anthropic's prompt cache still hits.
5. Rehydration on the response side round-trips through the same vault, so the next turn's re-anonymization produces identical placeholders (cache-safe).

### 3.2 Component layout (relative to `src/piighost/`)

```
proxy/                       NEW
├── __init__.py
├── __main__.py              entrypoint for `piighost proxy run`
├── server.py                Starlette + uvicorn TLS app
├── rewrite_request.py       anonymize inbound JSON
├── rewrite_response.py      rehydrate outbound SSE
├── stream_buffer.py         tail buffer for split placeholders
├── upstream.py              httpx forward to api.anthropic.com
├── handshake.py             reuses daemon/handshake.py pattern
└── audit.py                 per-request NDJSON audit

install/                     EXTEND (do not replace)
├── __init__.py              + ca_setup, service_setup, hosts_setup steps
├── ca.py                    NEW — generate & trust local root CA
├── service.py               NEW — launchd / systemd / schtasks registration
├── hosts_file.py            NEW — edit /etc/hosts with atomic backup
├── host_config.py           NEW — write ANTHROPIC_BASE_URL for Claude Code
└── (existing files unchanged)

cli/commands/                EXTEND
├── proxy.py                 NEW — piighost proxy run|status|logs
├── doctor.py                NEW — piighost doctor
└── uninstall.py             NEW — piighost uninstall

resources/                   NEW
└── service/
    ├── launchd.plist.j2
    ├── systemd.service.j2
    └── scheduled_task.xml.j2
```

The proxy shares `AnonymizationPipeline`, `Vault`, `ProjectRegistry`, and `PIIGhostService` with the existing MCP and daemon surfaces. One engine, three wire surfaces.

## 4. Wire-level rewriting

### 4.1 Request (anonymize)

Anthropic `/v1/messages` request body:

| Field | Action | Rationale |
|---|---|---|
| `messages[].content` (string or blocks) | anonymize | primary user input |
| `tool_result` blocks inside messages | anonymize | file reads, grep, bash output |
| `system` | anonymize | user may have dropped PII into system prompt |
| `tool_use.input` (assistant-authored) | anonymize | args may echo PII from earlier turns |
| `metadata.user_id` | hash (opaque) | identifier, not content |
| `tools[].description`, `tools[].input_schema` | pass through | schemas carry no user PII |
| `model`, `max_tokens`, `temperature`, etc. | pass through | scalars |

`cache_control` blocks are preserved byte-identical across requests — placeholder determinism comes from the per-project vault, so cached prefixes still hit.

### 4.2 Response (rehydrate)

Anthropic streams SSE events. Only two delta types carry bytes needing rehydration:

- `text_delta` — assistant text output
- `input_json_delta` — incremental JSON for `tool_use` arguments

Both are rehydrated through the project's vault. Assistant text needs rehydration so the user reads natural language. `tool_use.input` needs rehydration because the host will execute the tool locally with the rehydrated arguments.

### 4.3 Split-placeholder handling

A placeholder like `<PERSON:a3f8b2c1>` can arrive across multiple deltas. The stream buffer (`stream_buffer.py`) holds up to 64 bytes of trailing data per content block. On each delta:

1. Append to buffer.
2. Scan for complete placeholder patterns.
3. Rehydrate complete matches; emit prefix.
4. Retain any trailing partial (`<`, `<PER`, `<PERSON:a3f`) for next delta.
5. On `content_block_stop`, flush.

Buffer overflow (pathological case: placeholder > 64 bytes) force-flushes as-is and logs an audit event.

### 4.4 Failure modes

| Failure | Behavior |
|---|---|
| Pipeline / detector unreachable | HTTP 503 to host, no forwarding |
| Anonymization raises on a field | HTTP 500 with error, no forwarding |
| SSE stream breaks mid-rehydration | flush buffer, close stream, audit event |
| No active project | HTTP 409 with "run `piighost project use ...`" hint |
| Vault write fails | HTTP 500, no forwarding |
| Upstream Anthropic returns error | pass-through (error bodies don't contain user PII) |

Fail-closed is mandatory. A failed request is always better than a leak.

## 5. Install strategy

Two modes, both driven by the existing `piighost install` entrypoint.

### 5.1 Light mode — `piighost install --mode=light`

Claude Code CLI only. One admin prompt: the CA trust install (unavoidable — Claude Code validates TLS against OS trust store).

Steps added to existing `install/__init__.py::run`:

1. Generate local root CA and leaf cert for `localhost` (via Python `cryptography`).
2. Install CA into OS trust store — same mechanism as strict mode §5.2 step 2 (prompts for admin password once).
3. Start proxy background service bound to `127.0.0.1:8443` — unprivileged port, runs as user.
4. Write `ANTHROPIC_BASE_URL=https://localhost:8443` to Claude Code's config (`~/.claude/settings.json`) and to user-level env (`setx` / `launchctl setenv` / `~/.config/environment.d/`).

Claude Desktop and Cowork are **not** covered in light mode. They ignore `ANTHROPIC_BASE_URL`.

### 5.2 Strict mode — `piighost install --mode=strict`

All three hosts. Proxy binds to `127.0.0.1:443` (hosts-file redirect points `api.anthropic.com` there). Requires one-time admin/sudo prompts: one for CA trust, one for privileged port binding (macOS/Linux only).

Steps:

1. Generate local root CA using Python `cryptography` library — no external binary dependency. Store at `~/.piighost/proxy/ca.{pem,key}`.
2. Install CA into OS trust store:
   - **macOS:** `security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.pem` (prompts for admin password).
   - **Windows:** `certutil -addstore -f Root ca.pem` (elevates UAC).
   - **Linux:** copy to `/usr/local/share/ca-certificates/piighost.crt` + `update-ca-certificates` (Debian/Ubuntu) or `trust anchor ca.pem` (Fedora/RHEL). `sudo` required.
3. Issue leaf cert for `api.anthropic.com` signed by local CA. Store at `~/.piighost/proxy/leaf.{pem,key}`.
4. Grant proxy permission to bind `127.0.0.1:443`:
   - **Linux:** systemd socket unit owned by root that hands the listening FD to the user-level `piighost-proxy.service`. Avoids the fragile `setcap` path (reinstalling `uv` recopies the interpreter).
   - **macOS:** single `/Library/LaunchDaemons/com.piighost.proxy.plist` loaded as root, drops to the installing user via `UserName`. No separate user agent.
   - **Windows:** no elevation needed for port binding.
5. Edit hosts file with atomic backup:
   - `/etc/hosts` (macOS/Linux) or `C:\Windows\System32\drivers\etc\hosts` (Windows).
   - Append `127.0.0.1 api.anthropic.com` inside a sentinel block:
     ```
     # BEGIN piighost
     127.0.0.1 api.anthropic.com
     # END piighost
     ```
   - `hosts_file.py` writes a `.piighost.bak` copy before modifying.
6. Register background service (same file created in step 4 on macOS/Linux):
   - **macOS:** `/Library/LaunchDaemons/com.piighost.proxy.plist` (already written in step 4).
   - **Linux:** `systemd` unit triggered by the socket unit from step 4.
   - **Windows:** Scheduled Task "At log on" via `schtasks.exe` (user-level; no elevation).
7. Link existing hacienda plugin manifests to installed plugin dirs (unchanged from today's `claude_config.py`).
8. Probe: send a dummy anonymization through `https://api.anthropic.com` (which now resolves to the proxy). Assert round-trip succeeds and leaves no raw PII in the upstream capture.

### 5.3 Subcommand surface

Added to the existing Typer app at `cli/main.py`:

```
piighost install [--mode=light|strict] [--dry-run] [--force]
piighost uninstall [--purge-ca] [--purge-vault]
piighost doctor                         full health check
piighost proxy run                      foreground (debug)
piighost proxy status                   uses daemon/handshake pattern
piighost proxy logs                     tail audit log
```

Existing subcommands (`init`, `anonymize`, `rehydrate`, `detect`, `index`, `query`, `serve`, `vault`, `daemon`, `projects`, `docker`, `self-update`) are untouched.

### 5.4 Uninstall guarantee

`piighost uninstall` reverses install in strict reverse order:

1. Stop and deregister background service.
2. Revert hosts file from `.piighost.bak`.
3. Remove leaf cert.
4. Unset `ANTHROPIC_BASE_URL` env var and config entry (light mode only).
5. Remove privileged-port grant: unload LaunchDaemon (macOS), disable + remove systemd socket unit (Linux). No-op on Windows.
6. `--purge-ca` (explicit opt-in): remove root CA from OS trust store.
7. `--purge-vault` (explicit opt-in): delete `~/.piighost/`.

Plugin manifests are left alone — the user's hosts manage their own plugin dirs.

## 6. Audit & observability

### 6.1 Per-request audit record

Append-only NDJSON at `~/.piighost/audit/<YYYY-MM>/sessions.ndjson`:

```json
{
  "ts": "2026-04-24T14:03:21Z",
  "request_id": "req_01H...",
  "project": "client-dupont",
  "host": "cowork",
  "model": "claude-opus-4-7",
  "entities_detected": [
    {"label": "PERSON", "count": 2},
    {"label": "ADDRESS", "count": 1}
  ],
  "placeholders_emitted": 3,
  "request_bytes_in": 4821,
  "request_bytes_out": 4732,
  "stream_duration_ms": 3421,
  "rehydration_errors": 0,
  "status": "ok"
}
```

Raw PII, raw text, and placeholder→entity mapping stay in the project vault. Audit is safe to export to a DPO.

### 6.2 Metrics endpoint

Optional — off by default, opt in via `piighost install --metrics`. Exposes Prometheus format on `127.0.0.1:8444/metrics`:

```
piighost_requests_total{project,status}
piighost_entities_detected_total{label}
piighost_rehydration_buffer_overflow_total
piighost_stream_chunks_total
```

### 6.3 Integration with existing `hacienda:audit` skill

`plugin/skills/audit/SKILL.md` already reads `~/.piighost/audit/`. It extends naturally to proxy-generated events — no plugin change required.

## 7. Testing

| Layer | Harness | Proves |
|---|---|---|
| Unit — `rewrite_request` | pytest, fixture JSON bodies | every Anthropic message shape anonymizes correctly |
| Unit — `rewrite_response` | pytest, synthetic SSE streams | tail buffer handles placeholder splits |
| Integration — proxy loopback | pytest + aiohttp mock upstream | end-to-end anon → forward → rehydrate round-trip |
| Integration — MCP | existing piighost tests | no regressions |
| Cross-platform install | GH Actions matrix (macos-latest, ubuntu-latest, windows-latest) | `install → doctor → uninstall` exits 0 on all three |
| Leak scenario | pytest fixture: PII in prompt, mock Anthropic server records all received bytes, denylist regex derived from vault content | zero raw PII strings reach upstream |
| Red-team | reuse `bloom_auditor` profiles against proxy | prompt-injection can't exfil PII |

The **leak scenario test** is the lynchpin. It runs in CI against every PR and blocks merge on any denylist hit.

Manual verification (not CI-runnable):

- Cowork sandbox honors host's hosts-file redirect. Run `piighost install --mode=strict` on a test machine, open Cowork with a test project, trigger a chat turn, verify the proxy audit log records the request. If the sandbox has its own DNS resolver, this test fails — see Open Question #1.

## 8. Open questions

1. **Does the Cowork sandbox honor the host's `/etc/hosts`?** If the VM uses a separate DNS resolver, hosts-file redirection fails inside it and Cowork support is blocked in v1. Empirical test required before GA — see §7 manual verification. Current assumption: works (host OS resolves DNS and terminates TLS for the sandbox's outbound traffic).
2. **Anthropic Terms of Service.** A user-side MITM proxy that rewrites API traffic is unusual. The user is the controller and consents, but confirm this isn't prohibited before publishing widely.
3. ~~Linux port 443 binding~~ **Resolved** — systemd socket unit approach chosen (§5.2 step 4). Listed here for historical context only.
4. **Prompt cache verification.** Byte-identical placeholder emission across turns is guaranteed by design, but needs empirical confirmation against the live Anthropic API. Small cost, high value.
5. **macOS admin UX.** Strict mode on macOS prompts for admin password twice (once for CA, once for LaunchDaemon). Consider bundling both into a single `osascript` elevated block.
6. **Cert renewal.** Local CA validity = 10 years (chosen). Leaf cert validity = 1 year, auto-reissued on service restart if <30 days remaining. Needs silent-renewal code.

## 9. Rollout phases

1. **Phase 1 — proxy + Claude Code (light mode).** Build the proxy, ship light-mode install. Verify against Claude Code CLI. Alpha-pilot with technical users.
2. **Phase 2 — strict mode, Claude Desktop support.** Add CA install, hosts-file logic, privileged port binding. Verify Claude Desktop end-to-end. Beta.
3. **Phase 3 — Cowork verification.** Answer Open Question #1. If sandbox honors hosts file → GA for all three hosts. If not → document Cowork as "light-mode experimental" and file upstream FR with Anthropic.
4. **Phase 4 — default strict.** `piighost install` with no flags defaults to strict mode once all three hosts are proven.

## 10. Migration from today's install

Users currently install via:

```
uvx --from piighost[gliner2] piighost serve    # inside plugin/.mcp.json
# OR
piighost install                               # MCP + Claude Desktop config only
```

After this spec ships:

- `piighost install` (no flags) still works but now runs **light mode** by default. Backwards-compatible: MCP + Claude Desktop config registration continues.
- `piighost install --mode=strict` opts into the new proxy-backed enforcement.
- The hacienda plugin's `.mcp.json` and skills stay unchanged. Users who installed via the plugin see no breakage; if they run `piighost install --mode=strict` they get strict enforcement without touching the plugin.
- `plugin/skills/redact-outbound/SKILL.md` can shed most of its "remember to anonymize first" prose once strict mode is default — but not until Phase 4.
