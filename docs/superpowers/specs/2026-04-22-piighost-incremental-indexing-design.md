# piighost Incremental Indexing Design

**Date:** 2026-04-22
**Status:** Draft (awaiting user review)
**Author:** Incremental indexing brainstorm session

## Problem Statement

Currently, `piighost index_path()` is an all-or-nothing operation: every call re-processes every supported file in the folder, paying the full NER + embeddings cost regardless of whether the content changed. In Cowork scenarios where users continuously add documents to client folders throughout a session, this creates two problems:

1. **Wasted compute** — re-running gliner2 NER and multilingual-e5 embeddings on unchanged files is expensive (both latency and CPU)
2. **Poor UX** — users have no idea when new documents become searchable; they must manually re-run the entire index and wait through the full pipeline

New documents added to a watched folder are not indexed automatically, and the only way to make them searchable is a full re-index.

## Goals

- New and modified documents become searchable without full re-indexing
- Unchanged documents are skipped (no wasted NER/embeddings cost)
- No background polling or file watchers required (works within MCP request/response model)
- Cowork-friendly: no hooks needed, pure MCP tool-driven flow
- Production-ready: reliable, observable, recoverable

## Non-Goals

- Real-time (sub-second) freshness — batching is acceptable
- Filesystem watchers or kernel-level change notification
- Cross-machine index synchronization
- Automatic cleanup of deleted files (tracked, but not purged from embeddings store in v1)

## Architecture

The core insight: **piighost is called on-demand via MCP tools**. We don't need a background daemon — we can detect changes *lazily*, when any MCP tool is called, at essentially zero cost. Expensive work (NER + embeddings) runs only on files that genuinely changed.

### Components

1. **Metadata store** — SQLite table tracking what has been indexed, file fingerprints, and status
2. **Change detector** — Compares current folder state against metadata store (mtime+size → hash)
3. **Batch accumulator** — Groups detected changes and routes them into one of three tiers by size
4. **Tiered scheduler** — Decides whether to auto-index silently, ask once per session, or always ask
5. **Indexer** — Processes approved batch: runs NER + embeddings, updates metadata, isolates per-file failures

### Data Flow

```
User adds documents to folder
            ↓
User calls any MCP tool (query, index_path, etc.)
            ↓
Change detector scans folder, compares vs SQLite metadata
            ↓
      ┌─────┴──────┐
      │            │
  No changes   Changes found
      │            │
  Proceed as   Batch accumulator classifies size:
   normal      ┌───┼────────────┐
               │   │            │
            small medium       large
          (auto) (ask-once)  (always ask)
               │   │            │
               ↓   ↓            ↓
         Indexer processes approved batches
               ↓
         NER + embeddings on each file
               ↓
         Update SQLite metadata (success or error per file)
               ↓
         Report result back via tool response
```

## Component Design

### 1. Metadata Store (SQLite)

Table `indexed_files`:

```sql
CREATE TABLE indexed_files (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_mtime REAL NOT NULL,           -- Unix timestamp (float for subsecond)
    file_size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,         -- SHA-256 hex
    indexed_at REAL NOT NULL,           -- Unix timestamp
    status TEXT NOT NULL,               -- 'success' | 'error' | 'deleted'
    error_message TEXT,                 -- NULL unless status='error'
    entity_count INTEGER,               -- NULL unless status='success'
    chunk_count INTEGER,                -- NULL unless status='success'
    schema_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(project_id, file_path)
);

CREATE INDEX idx_indexed_files_project ON indexed_files(project_id);
CREATE INDEX idx_indexed_files_status ON indexed_files(project_id, status);
```

**Why SQLite:**
- Transactional integrity (rollback on partial batch failure)
- Queryable (debugging, auditing, observability)
- Separates indexing metadata from PII vault (schema hygiene)
- Scales from 10 to 10,000+ files without tuning

**Location:** `{data_dir}/projects/{project_id}/indexing.sqlite`

### 2. Change Detector

Input: folder path, project ID
Output: `{new: [...], modified: [...], deleted: [...], unchanged: [...]}`

Algorithm:
1. List all supported files in folder (via existing `list_document_paths`)
2. Load metadata rows for project from SQLite
3. For each file on disk:
   - Not in metadata → **new**
   - In metadata, mtime and size match → **unchanged** (skip — no hash needed)
   - In metadata, mtime or size differs → compute SHA-256:
     - Hash matches stored hash → **unchanged** (mtime touched without content change, e.g., `touch` or git checkout)
     - Hash differs → **modified**
4. For each metadata row with no corresponding file on disk → **deleted**

Performance target: <500ms for 1,000-file folder where no files changed (mtime+size check is O(N) stat calls, no content I/O).

### 3. Batch Accumulator & Tiered Scheduler

Given the detector output, classify by size:

| Tier | Criteria | Behavior |
|---|---|---|
| **Small** | ≤2 files AND total size <5 MB | Auto-index silently during next MCP call; report in tool response |
| **Medium** | 3-10 files OR 5-50 MB total | Ask once per session: *"Found N new docs. Index now?"* |
| **Large** | >10 files OR >50 MB | Always ask with estimated time based on recent per-file latency |

Session state lives in `daemon_state` (in-process) with a session ID keyed by project. Session ends when daemon idles past `idle_timeout_sec` or process exits.

Thresholds are constants in `piighost/service/config.py` (tunable per deployment).

### 4. Indexer

Processes an approved batch of files. For each file:

1. Extract text via kreuzberg
2. Chunk text (existing logic)
3. Run gliner2 NER on chunks → get entities
4. Anonymize chunks (replace entities with placeholders, store originals in vault)
5. Generate embeddings on anonymized chunks via multilingual-e5
6. Store chunks + embeddings in LanceDB
7. Update SQLite: `status='success'`, `entity_count`, `chunk_count`, `indexed_at=now`

**Error handling:**
- Per-file `try/except` — failure on one file does not affect others
- On exception: log error, update SQLite with `status='error'` and `error_message`, continue batch
- If SQLite commit fails (disk full, lock contention, etc.), roll back entire batch transaction — no partial metadata writes

**Transactions:**
- Begin SQLite transaction at batch start
- Commit after all files processed (success or error)
- Rollback on SQLite-level failure only; per-file errors are recorded as rows, not exceptions

### 5. MCP Surface Changes

**Modified tools:**

- `index_path(path, project, recursive=True, force=False)`
  - **Default behavior change**: incremental mode — only processes new/modified files
  - Returns: `{indexed, skipped, modified, unchanged, errors, duration_ms, project}`
    - Previously returned `{indexed, skipped, unchanged, errors, ...}`
    - New fields: `modified` (int) — files re-indexed because content changed
  - `force=True` preserves old behavior (re-index everything)

**New tools:**

- `check_folder_changes(folder)` — Read-only diff. Returns detector output without indexing.
  - Returns: `{new: [...], modified: [...], deleted: [...], unchanged_count: N}`
  - Useful for Claude to decide what to ask the user before calling `index_path`
- `cancel_indexing(project)` — Safety mechanism. Interrupts an in-progress batch.
  - Currently-processing file completes (can't kill NER mid-inference cleanly)
  - Remaining files are skipped; SQLite transaction rolls back
  - Returns: `{cancelled: bool, files_processed: int, files_skipped: int}`

**Unchanged tools:**

- `query()`, `anonymize_text()`, `rehydrate_text()`, `vault_*` — no interface changes
- `query()` will trigger a silent `check_folder_changes` on the project's folder and auto-index the small tier before running the query (transparent freshness)

### 6. Migration

On first run with incremental-indexing code against an existing project:

1. Detect missing `indexed_files` table → create it
2. Scan existing LanceDB chunks for unique `file_path` values
3. For each file on disk (that exists in LanceDB): compute current mtime, size, SHA-256 → insert row with `status='success'`
4. Users don't re-pay NER/embeddings cost; only pay one-time mtime+size+hash scan

If a file is in LanceDB but missing from disk, mark `status='deleted'` in backfill.

`schema_version=1` is stored on every row. Future schema changes bump version and trigger a targeted migration.

## Error Handling Reference

| Failure Mode | Behavior |
|---|---|
| Corrupted PDF fails extraction | File marked `status='error'`, batch continues |
| NER model OOM on one file | File marked `status='error'`, batch continues, subsequent files may succeed after garbage collection |
| LanceDB write fails | File marked `status='error'`, batch continues |
| SQLite disk full | Transaction aborts, all batch files retain previous status (no writes) |
| Process killed mid-batch | SQLite rolls back on reconnect — partial state never visible |
| User calls `cancel_indexing` | Current file finishes, remaining skipped, batch rolls back |

## Testing Strategy

### Unit

- Change detector: new/modified/unchanged/deleted classification against fixtures
- Hash is computed only when mtime or size differs (verify via spy/mock)
- Batch tier classification (small/medium/large) across edge sizes
- SQLite rollback on simulated write failure
- Migration backfill against a pre-incremental project fixture

### Integration

- Add 5 `.txt` files → `index_path()` → add 3 more `.txt` files → `index_path()` — assert only 3 processed second time
- Modify existing file (overwrite with new content) → assert file re-indexed, entity count updated
- Delete file from disk → `check_folder_changes` reports it as deleted
- Include corrupted PDF in batch → good files index, bad one recorded as error
- Multi-project isolation: changes in project A do not trigger scans in project B

### End-to-End

- Full MCP workflow via `piighost serve --transport stdio`:
  - Claude calls `query()` → silent small-batch auto-indexes 2 new files → query returns fresh results
  - Claude calls `check_folder_changes()` → sees 8 new files → asks user → user approves → `index_path()` processes batch
- `force=True` preserves old behavior (full re-index) — regression check

### Performance

- 1,000-file folder with 10 new files: detection + indexing < full-re-index / 10 (10x speedup floor)
- 1,000-file folder, zero changes: detection < 500ms wall clock

## Open Questions

None at design time. Implementation may surface edge cases around LanceDB chunk cleanup for deleted files (deferred to a follow-up spec).

## Design Summary

| Component | Decision |
|---|---|
| Metadata storage | SQLite `indexed_files` table, per-project |
| Detection trigger | Lazy — runs only when MCP tool is called |
| Change detection | mtime + size (fast path); SHA-256 on changed files only |
| Batching | Tiered: small (auto), medium (ask once/session), large (always ask) |
| Batch threshold | 5 files OR session end (medium tier) |
| Error handling | Per-file isolation; skip-and-log; SQLite transaction rollback on catastrophic failure |
| MCP surface | `index_path` incremental by default; new `check_folder_changes`, `cancel_indexing` |
| Migration | Auto-backfill metadata from existing LanceDB on first run |
| Deleted files | Tracked in metadata (status='deleted'); LanceDB cleanup deferred |
