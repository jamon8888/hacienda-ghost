---
name: knowledge-base
description: Search and answer questions from the user's current Cowork folder using PII-safe hybrid retrieval (BM25 + semantic vectors, cross-encoder reranker). Use whenever the user asks about documents, emails, contracts, notes, invoices, or any content in the folder Cowork is currently pointed at. Always cites sources with file paths and excerpts. Placeholders like «PER_001» in retrieved excerpts are intentional — see the redact-outbound skill before including them in any draft sent to external tools (email, Slack, webfetch).
---

# knowledge-base — PII-safe retrieval over the current folder

This skill powers the `/ask` slash command and is implicitly used whenever the user asks about their files. It wraps the `piighost` MCP server (aliased as `hacienda`) and is the only sanctioned way to read folder contents.

## Why this exists

The user is bound by professional secrecy (*secret professionnel*, GDPR Art. 32, equivalent). Raw folder contents cannot be read into the model context unredacted and then paraphrased outbound — every outbound request would leak identifiable client data.

Piighost has already solved this: every retrieval tool returns text where PII has been replaced with opaque placeholders (`«PER_001»`, `«IBAN_003»`, `«ORG_014»`). The vault stores ciphertext; the plugin rehydrates placeholders only for display, never for the model's working context.

**Your job in this skill:** call the right MCP tools, never read raw files via the `Read` tool for content in a Cowork-shared folder, and always cite sources.

## Workflow

### Step 1 — Resolve the active folder

Cowork tells you the active folder path. Call:

```
mcp__hacienda__resolve_project_for_folder(folder=<abs_path>)
```

Returns `{"folder": ..., "project": "<slug>-<hash8>"}`. Use `project` in every subsequent call so cross-folder retrieval is impossible.

### Step 2 — Bootstrap (idempotent)

On the first question of a session, call:

```
mcp__hacienda__bootstrap_client_folder(folder=<abs_path>)
```

This is cheap on re-run. It ensures the data dir, vault key, and project exist.

### Step 3 — Check index status

Read the resource:

```
piighost://folders/{b64_path}/status
```

where `b64_path = base64.urlsafe_b64encode(folder.encode()).decode().rstrip("=")`.

> **Note on the URI scheme.** MCP resource URIs are opaque strings owned by the server — they are NOT rewritten by the `hacienda` alias in `.mcp.json`. Tool names get the `mcp__hacienda__*` prefix; resource URIs keep their server-declared scheme, which is `piighost://`.

- `state == "empty"`: tell the user *"Indexing this folder — I'll answer as soon as it's ready. You can also run `/index` to force a full scan."* and call `mcp__hacienda__index_path(path=<folder>, project=<project>)` in the background.
- `state == "ready"`: proceed.
- `errors` non-empty: surface the error list to the user; suggest `/index`.

(The v0 resource only emits `empty` or `ready` — there is no distinct `indexing` state. A running index simply shows `empty` until the first chunks land, then `ready`.)

### Step 4 — Retrieve

```
mcp__hacienda__query(
  text=<user question>,
  k=5,
  project=<project>,
  rerank=true,
  top_n=20,
)
```

The returned excerpts are already redacted. Quote them verbatim.

### Step 5 — Answer with citations

Every claim cites `<filename> p.<page>` (for PDFs) or `<filename>:<line-range>` (for text). If retrieval returns nothing, say so — never fabricate a citation.

### Step 6 — Record the audit event

Once per user turn, append:

```
mcp__hacienda__session_audit_append(
  session_id=<project>,
  event="query",
  payload={"question_hash": <sha256_hex_of_question>, "n_excerpts": <n>, "project": <project>},
)
```

Use the `project` name as `session_id` — that scopes the audit log to one JSONL file per folder (`~/.hacienda/sessions/<project>.audit.jsonl`), which is what the user wants for compliance review. Cowork does not expose a per-conversation ID, and a per-folder log aggregates across conversations without losing any forensic value.

`question_hash` is `hashlib.sha256(question.encode("utf-8")).hexdigest()` (lowercase hex). Keeping the hash — never the raw question — lets `/audit` report query volume without storing identifiable content.

## Outbound content

If the user asks you to draft a reply, email, Slack message, or to call `WebFetch` with folder content:

- Treat every excerpt as **already anonymised** — the placeholders are the correct content to send.
- If the user types a real name in chat (e.g. *"reply to Jean Martin"*), call `mcp__hacienda__anonymize_text` on any folder-derived text you include in the draft, then merge.
- See the `redact-outbound` skill for placeholder semantics.

## Refusals

- If the user asks about a folder that is *not* the currently open Cowork folder, refuse and suggest switching folders. Never accept a folder path as a prompt argument.
- If `vault_key_provisioned` from bootstrap is false, refuse — something is broken upstream.

## Edge cases

- Network drive (`Z:\`, `\\server\share`): watchers are unreliable. If `state == "ready"` but `last_update` is >10 minutes old, warn the user and suggest `/index`.
- Folder with >5 000 files: indexing may take several minutes. The first query after `/index` can return fewer results than expected — re-running the query once the status chip shows `ready` is the fix.

## Never do

- Never read files in the Cowork folder with the built-in `Read` tool for content use — only for file type inspection (extension, size). All content must come through `mcp__hacienda__query`.
- Never pass a `folder` argument the user typed. Only use the Cowork-declared active folder.
- Never log raw PII in `session_audit_append`. Pass hashes, placeholders, or counts.
