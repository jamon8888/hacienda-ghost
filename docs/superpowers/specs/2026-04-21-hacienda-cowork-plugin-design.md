# Hacienda — Claude Desktop Cowork Plugin Design

**Status:** Draft for review
**Date:** 2026-04-21
**Author:** piighost team
**Next step after approval:** invoke `superpowers:writing-plans` to create the implementation plan.

---

## 1. Context & Problem

Claude Desktop shipped **Cowork** in January 2026 as its agentic workflow surface ("Chat is for conversations. Cowork is for workflows."). Cowork can read local folders and mapped network drives, run MCP servers, load plugins with skills/commands/hooks, and surface status resources in the sidebar.

The Cowork marketplace is almost empty. As of this spec, only one widely-installed third-party plugin exists (Slack). There is **no plugin** that lets a regulated professional drop a client folder onto Claude Desktop and work on it safely under *secret professionnel*.

Regulated professionals (lawyers, notaries, expert-comptables, doctors, financial advisors) cannot use generic Claude Desktop workflows on client data because:

1. **Professional secrecy (Article 226-13 Code pénal)** forbids sending identifiable client data to a US-hosted LLM without specific safeguards.
2. **GDPR Art. 32** requires appropriate technical measures — raw prompts to api.anthropic.com do not qualify.
3. **Client folders are chaotic**: mixed PDFs, DOCX, XLSX, emails, scans. Cowork's default read-file loop is too slow and too context-hungry to be useful over hundreds of documents.
4. **There is no affordance** in Cowork today for "this is Client A's folder, keep it isolated from Client B."

piighost already solves most of this at the infrastructure layer: a local MCP server with per-project isolation, a PII vault with deterministic placeholders, BM25+vector hybrid retrieval, and a cross-encoder reranker. What's missing is the Cowork-native **product layer** that packages those capabilities as a plugin a non-technical professional can install in two clicks.

**Hacienda** is that plugin.

---

## 2. Product Identity & Positioning

**Name:** `hacienda`
**Tagline:** *The Cowork plugin that makes Claude Desktop safe under professional secrecy.*
**One-liner:** PII-safe RAG over your client folders, directly inside Claude Desktop.

**Why the name:** A *hacienda* is a walled estate — a controlled, defensible perimeter around valuable assets. Each client folder becomes a hacienda: isolated, auditable, protected.

**Positioning vs. alternatives:**

| Alternative | Why it falls short for regulated pros |
|---|---|
| Raw Cowork + local folders | No PII protection; every prompt ships identifiable data to Anthropic. |
| Claude Enterprise / Teams | Does not remove PII from prompts; contractual DPA only. |
| NotebookLM, Copilot, ChatGPT Projects | US clouds; no redacted-transit; no local inference fallback. |
| Custom in-house RAG | Months of work; no Cowork integration; no marketplace distribution. |

**Target user cluster (generic, no vertical specialization):** any professional bound by *secret professionnel* or equivalent confidentiality duty — avocats, notaires, experts-comptables, médecins, conseils en propriété industrielle, CGP/CIF. We pick the cluster by legal obligation, not by profession, so one plugin serves the whole market.

---

## 3. User Persona & Scenarios

**Persona — Maître Lefèvre, avocat en droit des affaires:**
- Runs a 3-lawyer firm. Tech comfort: normal professional (Word, Outlook, iManage).
- Wants to use Claude Desktop for drafting and research but cannot legally paste client files into it.
- Has a Windows laptop; client folders live on a network share (`Z:\Dossiers\<Client>\`).
- Cannot self-host infrastructure. Will install a plugin from the marketplace. Will not write YAML.

**Scenario 1 — Brief on arrival:**
1. Maître opens Cowork, selects the folder `Z:\Dossiers\ACME\`.
2. A status chip appears: *"Hacienda · indexing 247 files (32%)"*.
3. Types: *"What are the outstanding deliverables from ACME under the 2024 SaaS contract?"*
4. Claude invokes the `knowledge-base` skill, runs `hybrid_search`, reads the top 5 excerpts (already redacted by the vault), drafts an answer citing `contrat-saas-2024.pdf p.12` and `email-2025-11-03.eml`.
5. Before the answer leaves the laptop, the redaction hook has already replaced the 12 personal names, 4 IBANs, and 2 phone numbers with placeholders.
6. When the answer comes back, the rehydration hook restores real names locally so Maître reads *Jean Martin*, not *«PER_001»*.

**Scenario 2 — Cross-client isolation:**
- Maître never says "which client." Claude only ever sees the folder currently opened in Cowork.
- Switching folder = switching project in piighost. No leakage.

**Scenario 3 — Audit trail:**
- `/hacienda:audit` dumps a per-session report: which files were read, what placeholders were generated, what went to the cloud, what came back.

---

## 4. Scope

### In scope (v1.0 — marketplace launch)

- **Plugin manifest + marketplace metadata** — installable from official Anthropic marketplace.
- **Bundled piighost MCP server** (vendored) — zero external install steps.
- **`knowledge-base` skill** — THE core skill; maps Cowork's current folder to a piighost project, drives hybrid retrieval, cites sources.
- **`redact-outbound` skill** — describes when/why outbound redaction fires; guides the user when a placeholder appears.
- **Redaction seatbelt hooks** — PreToolUse on outbound tools (`Write`, `Edit`, `WebFetch`, `WebSearch`, any `*slack*`/`*gmail*`/`*email*`/`*docusign*`/`*drive*` MCP tool); PostToolUse on retrieval tools to rehydrate locally.
- **Slash commands (v1):**
  - `/hacienda:index [path]` — force (re)indexing of the current folder.
  - `/hacienda:kb-status` — show index state, doc count, last update, any errors.
  - `/hacienda:audit` — per-session report.
- **Slash commands (v1 stretch, week 4 of implementation):**
  - `/hacienda:brief` — structured intake summary of a client folder.
  - `/hacienda:draft-reply` — draft a reply to the last email in the folder using surrounding context.
- **Status surface (MCP resource):** `hacienda://kb/status` — Cowork renders this in the sidebar as a live chip.
- **Monitors:** one background monitor that watches the active folder via piighost's file watcher and posts *"3 new files indexed"* notifications when things change.
- **Indexing lifecycle:** hybrid **lazy + watcher**:
  - On folder open: enqueue full index (async, non-blocking).
  - On file change (local folders): filesystem watcher triggers re-index of that file only.
  - On network paths where watchers are unreliable: 10-minute poll fallback.
  - User-visible progress via the status resource.
- **Confidentiality model:** **redacted-transit**. Every prompt that leaves the laptop passes through the redaction hook first. Every result comes back through rehydration. Vault key stays local.
- **Localization:** EN + FR strings for every user-visible surface (command descriptions, skill descriptions, status messages, audit output).
- **License:** MIT (plugin code) + optional paid **support contracts** (SLA, onboarding, custom vertical profiles, priority bug fixes).

### Out of scope (v1.0)

- **Tiered-per-folder confidentiality** — deferred to V2. V1 ships single-mode redacted-transit.
- **Client manifest / folder-labeling UI** — we rely entirely on Cowork's native folder picker.
- **Non-French/English locales** — DE/IT/ES deferred.
- **Vertical-specific profiles** (avocat vs. notaire vs. expert-comptable) — v1 is generic. Verticals are a paid-support deliverable.
- **Online model switching** — v1 uses whatever Claude Desktop is configured to use.
- **Cloud sync between devices** — the hacienda data stays on one machine.
- **Hacienda-specific UI chrome** — we add nothing to Claude Desktop beyond the plugin contract.
- **Rewriting or replacing any piighost MCP tool** — v1 is pure packaging + configuration + prose + small hook scripts.

---

## 5. Architecture

### 5.1 Relationship to piighost

```
Claude Desktop (Cowork)
  └── Plugin: hacienda
        ├── skills/            (prose, model-invoked)
        ├── commands/          (prose, user-invoked)
        ├── agents/            (prose, subagent)
        ├── hooks/             (Python scripts, local-only)
        ├── monitors/          (local background process)
        ├── .mcp.json          → spawns vendored piighost MCP server
        └── vendor/piighost/   (bundled MCP server, uv-run)
                 │
                 └──── local only, no network calls ──── vault / index / watcher / search
```

**Invariant:** the plugin introduces **no new MCP server code**. Every capability it exposes is already an MCP tool on piighost. The plugin is pure configuration + prose + hook scripts on top.

### 5.2 File layout

```
hacienda/
├── .claude-plugin/
│   └── plugin.json                 # manifest: name, version, author, marketplace metadata
├── skills/
│   ├── knowledge-base/
│   │   └── SKILL.md                # THE core skill — hybrid search + citations
│   └── redact-outbound/
│       └── SKILL.md                # explains placeholder semantics to the model
├── commands/
│   ├── index.md                    # /hacienda:index
│   ├── kb-status.md                # /hacienda:kb-status
│   ├── audit.md                    # /hacienda:audit
│   ├── brief.md                    # /hacienda:brief  (stretch)
│   └── draft-reply.md              # /hacienda:draft-reply  (stretch)
├── agents/
│   └── redaction-agent.md          # subagent for large redaction audits
├── hooks/
│   ├── hooks.json                  # matcher → command wiring
│   ├── redact.py                   # PreToolUse: outbound redaction
│   └── rehydrate.py                # PostToolUse: rehydrate retrieval results locally
├── monitors/
│   └── monitors.json               # watcher notifications
├── .mcp.json                       # declares bundled piighost MCP server
├── settings.json                   # plugin-scoped settings
├── bin/
│   └── hacienda-bootstrap          # first-run helper: vault key, data dir
├── vendor/
│   └── piighost/                   # bundled MCP server (copied from piighost/bundles/full)
├── icon.png
├── LICENSE                         # MIT
└── README.md                       # user-facing install + usage
```

### 5.3 Data flow — redacted-transit

```
User prompt
    │
    ▼
Cowork/Claude Desktop
    │
    ├─(A) Local tool call: Read file in folder
    │         │
    │         ▼
    │    PostToolUse hook: rehydrate.py
    │    (no-op for Read — files on disk are already real)
    │
    ├─(B) Retrieval call: mcp__hacienda__hybrid_search
    │         │
    │         ▼  (piighost returns already-redacted excerpts — vault stores ciphertext)
    │    PostToolUse hook: rehydrate.py
    │    (optional: rehydrate for user-visible display only, not for model context)
    │
    └─(C) Outbound call: Write, Edit, WebFetch, *slack*, *gmail*, *drive*, *docusign*
              │
              ▼
         PreToolUse hook: redact.py
              │  scan tool_input for PII, replace with placeholders,
              │  log (placeholder → real) pairs into session audit file
              ▼
         Outbound request leaves with placeholders only
```

**Key property:** the model context is already redacted because piighost's search tools return redacted text. The outbound hook is defense-in-depth: it catches PII that reached the context through a non-piighost path (e.g., the user pasted a name into chat).

### 5.4 Core components

#### 5.4.1 `knowledge-base` skill (SKILL.md)

```yaml
---
description: >
  Search and answer questions from the user's current client folder using
  hybrid BM25 + semantic vector retrieval. Use whenever the user asks about
  documents, emails, contracts, notes, or any content in the folder Cowork
  is currently pointed at. Cite sources with file paths + excerpts.
allowed-tools:
  - mcp__hacienda__index_path
  - mcp__hacienda__hybrid_search
  - mcp__hacienda__remove_doc
  - mcp__hacienda__vault_get
  - ReadMcpResourceTool
---
```

Body guides the model to:
1. Resolve the active Cowork folder → piighost project name (deterministic hash of absolute path).
2. Check `hacienda://kb/status` — if not ready, call `index_path` and inform the user.
3. For every question, issue `hybrid_search` with top_k=10, reranker on.
4. Quote excerpts verbatim, cite `<filename> p.<page>` or `<filename>:<line-range>`.
5. If the user asks about a client whose folder is not currently open, refuse and suggest switching folders.
6. Never fabricate citations. If search returns nothing, say so.

#### 5.4.2 `redact-outbound` skill (SKILL.md)

Short skill that teaches the model what placeholders like `«PER_001»`, `«ORG_014»`, `«IBAN_003»` mean and how to handle them in drafts. No tools; pure prose.

#### 5.4.3 Redaction hooks (`hooks/`)

**`hooks.json`:**
```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Write|Edit|MultiEdit|WebFetch|WebSearch|.*slack.*|.*gmail.*|.*email.*|.*docusign.*|.*drive.*",
      "hooks": [{ "type": "command", "command": "python3 ${CLAUDE_PLUGIN_DIR}/hooks/redact.py" }]
    }],
    "PostToolUse": [{
      "matcher": "mcp__hacienda__hybrid_search|mcp__hacienda__vault_get",
      "hooks": [{ "type": "command", "command": "python3 ${CLAUDE_PLUGIN_DIR}/hooks/rehydrate.py" }]
    }]
  }
}
```

**`redact.py`** (stdin JSON → stdout JSON):
- Reads `tool_input` from stdin.
- Calls `mcp__hacienda__anonymize_text` via a short-lived MCP client (or directly via the local unix socket piighost daemon exposes).
- Replaces the text fields in `tool_input` with the redacted version.
- Emits `{"decision": "modify", "tool_input": <redacted>}`.
- Logs `(placeholder, real_value_ciphertext_handle)` into `~/.hacienda/sessions/<session_id>.audit.jsonl`.

**`rehydrate.py`**: symmetric — for display surfaces only (audit command, user-facing summaries), replaces placeholders back with real values from the vault.

#### 5.4.4 Status resource

Piighost already exposes `piighost://index/status`. The plugin's `.mcp.json` aliases the server under the name `hacienda`, so the resource URI becomes `hacienda://kb/status`. Cowork renders MCP resources in the sidebar automatically.

Content shape:
```json
{
  "folder": "Z:\\Dossiers\\ACME",
  "project": "acme-a1b2c3",
  "state": "indexing" | "ready" | "error",
  "progress": { "done": 79, "total": 247 },
  "last_update": "2026-04-21T14:32:11Z",
  "errors": []
}
```

#### 5.4.5 Monitors

`monitors/monitors.json` declares one long-running process that tails piighost's watcher event stream and emits one Claude notification per batch of indexed files. Opt-in via a setting so users can silence it.

#### 5.4.6 Slash commands

Each is a single Markdown file with a YAML header declaring `description` and optional `allowed-tools`. Bodies are prose instructions — the model executes them by calling the right MCP tools.

Example `commands/index.md`:
```yaml
---
description: Force (re)index the folder currently open in Cowork
allowed-tools:
  - mcp__hacienda__index_path
  - ReadMcpResourceTool
---
```
Body: *"Resolve the active Cowork folder path. Call `index_path` with `force_reindex=true`. Stream progress from `hacienda://kb/status`. Report final doc count and errors."*

### 5.5 Indexing lifecycle

```
Folder opened in Cowork
    │
    ▼
knowledge-base skill reads hacienda://kb/status
    │
    ├── state == "unknown" → call index_path (async)
    │                         status transitions: queued → indexing → ready
    │
    ├── state == "ready"   → proceed to hybrid_search
    │
    └── state == "error"   → inform user, surface errors, offer /hacienda:index

File change event (local paths)
    │
    ▼
piighost watcher → incremental re-index → monitor notification → Claude bubble

Network paths (Z:, \\server\share)
    │
    ▼
Watcher disabled (notifications unreliable) → 10-min poll → same pipeline
```

### 5.6 First-run bootstrap (`bin/hacienda-bootstrap`)

On first plugin activation:
1. Create `~/.hacienda/` (data dir).
2. Generate a vault key if none exists; store via OS keychain (macOS Keychain / Windows Credential Manager / libsecret).
3. Start the bundled piighost daemon.
4. Write a welcome note to the first Cowork session.

No dialog boxes, no config files for the user to edit.

---

## 6. Confidentiality Model (v1 — redacted-transit)

- **Vault:** piighost's existing AES-256-GCM vault; key in OS keychain.
- **Placeholder scheme:** `«TYPE_NNN»` — deterministic per (project, entity, type). Same IBAN gets the same placeholder across queries in the same project.
- **Leak surfaces covered:**
  - Retrieval results (via piighost's built-in anonymization on read).
  - Outbound tool calls (via the PreToolUse hook, defense-in-depth).
- **Leak surfaces NOT covered in v1:** the user typing a client's real name into the chat input. We mitigate with onboarding copy ("treat chat as if it were a letter you're mailing") and with the redaction hook scanning chat-originating payloads before they're sent outbound.
- **Audit trail:** per-session append-only JSONL in `~/.hacienda/sessions/`. `/hacienda:audit` surfaces it.
- **V2 upgrade path:** tiered-per-folder — each folder declares a confidentiality level (`public` / `internal` / `secret`) that adjusts hook aggressiveness and reranker depth. No schema change needed in v1; the folder→project mapping already exists.

---

## 7. Localization

All user-visible strings in EN + FR:
- `plugin.json` description fields
- Each `SKILL.md` / `command.md` description
- Status messages emitted by `redact.py`, `rehydrate.py`, `bin/hacienda-bootstrap`
- README

Language selection: follow Claude Desktop's UI locale at plugin load time. No runtime switching.

---

## 8. Distribution & Deployment

- **Primary channel:** Official Anthropic Cowork marketplace. Target v1.0 listing.
- **Secondary channel:** GitHub release (zip + mcpb) for self-service install.
- **Updates:** semver; Cowork handles update prompts.
- **Telemetry:** none by default. An optional opt-in anonymous install counter that hits a piighost-owned endpoint — disabled unless the user ticks a box in settings.

---

## 9. Licensing & Business Model

- **Plugin code:** MIT. Public repo at `github.com/jamon8888/hacienda` (separate from piighost to keep branding clean).
- **Paid offerings (invoice-based, out of the plugin itself):**
  - Onboarding workshop for firms (half-day, remote).
  - SLA / priority support (quarterly).
  - Custom vertical profiles (e.g., a notaire pack with notary-specific placeholder types, contract templates, and French civil-law prompts).
  - On-premise deployment support.
- **Pricing:** published on a separate site; the plugin itself never asks for payment or a license key.

This keeps the marketplace listing frictionless (free, no signup) while giving firms a clear path to buy professional support.

---

## 10. Non-Goals

- Not a DMS replacement. We don't own the folder; Cowork does.
- Not a Cowork fork. We add zero UI chrome.
- Not an LLM. We don't ship model weights.
- Not a cloud service. Nothing hacienda-specific runs off-device.
- Not a compliance certification. We enable *secret professionnel* workflows; we don't audit for them.

---

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Network drive watcher unreliable | Stale index on shared folders | 10-min poll fallback + visible "last update" in status chip |
| First-run indexing on a 10k-file folder is slow | User frustration | Async index with progress chip; `hybrid_search` works on the partial index |
| User pastes raw PII into chat | Leak to Anthropic | Outbound redaction hook catches it before it leaves; onboarding copy warns |
| Cowork plugin API changes before v1.0 | Ship delay | Track Anthropic plugin changelog; keep surface minimal |
| Bundled piighost diverges from main | Maintenance burden | CI job: rebuild hacienda on every piighost release; pin to tagged versions |
| Subagent redaction loops | Latency | Cap redaction audit at 5MB per tool call; degrade to "block + ask user" above |
| Someone markets a competitor first | Lost wedge | Ship marketplace listing in 6 weeks; we already have the backend |

---

## 12. V2 Roadmap (non-binding)

- **Tiered-per-folder confidentiality.**
- **Vertical profile packs** (notaire / avocat / expert-comptable).
- **Cross-folder search with explicit user consent** (for firm-wide research).
- **Local LLM fallback** via Ollama for fully-offline mode.
- **Cloud sync across devices** for multi-laptop users.
- **DE / IT / ES localization.**
- **Web-app companion** for non-Claude-Desktop users (firm-wide dashboard).

---

## 13. Success Criteria (v1.0)

- Marketplace listing live with FR + EN descriptions.
- Installable in two clicks with no CLI steps.
- First-time user can index a 1000-file folder and get a cited answer within 10 minutes.
- Zero raw-PII leakage in outbound requests across a 100-prompt smoke test.
- 50 installs in the first month. 5 paid-support conversations in the first quarter.

---

## 14. Open Questions (for user review)

1. **Repo location:** separate public repo `jamon8888/hacienda` vs. subdirectory in `piighost`? Spec currently assumes separate.
2. **Paid-support delivery entity:** same legal entity that owns piighost, or a new one? (Design-independent but affects README footer.)
3. **Icon:** we need a hacienda-themed icon (walled estate silhouette). Design task or external commission?
4. **Onboarding copy tone:** formal "Maître" / "Cher confrère" vs. modern professional ("Bonjour"). Default to modern professional unless told otherwise.
