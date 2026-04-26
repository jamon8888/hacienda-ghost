# folder_status errors[] — design

**Date:** 2026-04-26
**Status:** Spec — awaiting plan
**Author:** brainstorming session

## Problem

When `index_path` fails on individual files (corrupt PDF, password-protected
DOCX, unsupported format), the failure is reported in the synchronous return
value of that one call and then forgotten. The `/status` slash command in the
hacienda plugin can today say *"247 indexed, 1 823 chunks, ready"* even when 12
files silently failed at last index. The user has no way to discover those
failures except by re-running `/index` and reading the response.

The data exists. `IndexingStore.indexed_files` already persists every failed
file with `status='error'`, `error_message`, and `indexed_at`. There is even a
`(project_id, status)` SQLite index. We are throwing it away.

## Goal

Surface persisted file-level indexing errors through `folder_status` (and the
`piighost://folders/{b64}/status` MCP resource), so the plugin's `/status`
command can render *"3 files failed: contract.pdf — password-protected,
scan.pdf — corrupt, …"*.

## Non-goals

- **No change to `IndexReport.errors`.** That stays `list[str]` for backward
  compatibility; touching it churns tests across the codebase for no plugin
  benefit.
- **No new error sources.** Only persisted `status='error'` rows are surfaced.
  Errors that happen during a query, watcher event, or audit-log append are
  not in scope.
- **No retry/clear command.** Re-running `/index full` already flips fixed
  files back to `status='success'`; that is the retry path.
- **No pagination beyond `limit`.** If a user has > 50 broken files they have
  bigger problems; cursors can be added later if real demand appears.

## Architecture

```
indexed_files (SQLite, already populated)
  ↓
IndexingStore.list_errors(project_id, limit=50)        ← NEW
  ↓
piighost.service.error_taxonomy.classify()             ← NEW (pure)
  ↓
PIIGhostService.folder_status() includes errors[]      ← MODIFIED
  ↓
piighost://folders/{b64}/status MCP resource           ← shape extends
  ↓
hacienda plugin /status skill renders                  ← MODIFIED
```

## Components

### 1. `IndexingStore.list_errors`

`src/piighost/indexer/indexing_store.py`

```python
def list_errors(
    self,
    project_id: str,
    *,
    limit: int = 50,
) -> list[FileRecord]:
    """Return up to limit most-recent error rows for project_id,
    ordered by indexed_at DESC. Excludes 'success' and 'deleted'."""
```

Single SQL statement; the existing `(project_id, status)` index covers the
predicate. Also expose a sibling `count_errors(project_id) -> int` for the
truncation indicator (one COUNT query is cheaper than fetching all rows just
to size them).

### 2. Error taxonomy

`src/piighost/service/error_taxonomy.py` (NEW)

A pure function with no I/O:

```python
_TAXONOMY: tuple[tuple[str, str], ...] = (
    ("password",          "password_protected"),
    ("encrypted",         "password_protected"),
    ("could not decrypt", "password_protected"),
    ("corrupt",           "corrupt"),
    ("invalid pdf",       "corrupt"),
    ("malformed",         "corrupt"),
    ("unsupported",       "unsupported_format"),
    ("no extractor",      "unsupported_format"),
    ("not supported",     "unsupported_format"),
    ("timeout",           "timeout"),
    ("timed out",         "timeout"),
)

def classify(error_message: str | None) -> str:
    """Map a persisted error_message to a bounded category.

    Input is the raw value from indexed_files.error_message, which is
    stored as ``f"{type(exc).__name__}: {exc}"``. Matches case-insensitively
    against substrings in _TAXONOMY in declaration order; first match wins.
    Falls back to ``"other"`` for unrecognised messages and ``None`` input.

    Never returns the input string directly — raw exception text can contain
    file paths or document fragments that are PII."""
```

Categories returned are exactly:
`password_protected | corrupt | unsupported_format | timeout | other`.

The taxonomy is closed: any future category addition requires a code change,
which is intentional — the schema enumerates safe values. Documented in the
module docstring.

### 3. Pydantic model

`src/piighost/service/models.py`

```python
class FolderError(BaseModel):
    file_name: str        # basename only (safe to render)
    file_path: str        # full path (the user already owns this)
    category: str         # one of the taxonomy values
    indexed_at: int       # unix epoch seconds
```

The Python exception class name is *not* exposed as a separate field. The
persisted `error_message` column stores `f"{type(exc).__name__}: {exc}"` as
a concatenated string; rather than parse that prefix back out (brittle) or
add a new SQLite column (overkill for a debug field), we use the full
persisted string only as input to `error_taxonomy.classify()` and surface
only the bounded `category`. Server logs remain the source of truth for
debugging individual exceptions.

### 4. `folder_status` return shape

`src/piighost/service/core.py` — `folder_status` adds three fields:

```python
{
    "folder": str,
    "project": str,
    "state": "empty" | "indexed",
    "total_docs": int,
    "total_chunks": int,
    "last_indexed_at": int | None,
    # NEW:
    "errors": list[FolderError],     # up to 50, most recent first
    "errors_truncated": bool,         # True iff total_errors > 50
    "total_errors": int,              # total count, regardless of limit
}
```

Existing consumers see the unchanged top-level shape; the three new fields are
additive. When the project is unregistered or empty, `errors=[]`,
`errors_truncated=False`, `total_errors=0` — same fast-path.

### 5. MCP resource

`src/piighost/mcp/shim.py` — the `piighost://folders/{b64_path}/status`
resource is unchanged structurally; it forwards to `folder_status` and
returns whatever the service returns. No code change needed beyond the
service-layer update being picked up automatically.

### 6. /status skill

`hacienda-plugin/skills/status/SKILL.md` — replace the current
`Errors: <n>` line with:

```
Folder:       <absolute path>
Project:      <project hash>
State:        <indexed|empty>
Indexed docs: <total_docs>
Chunks:       <total_chunks>
Last update:  <last_indexed_at ISO 8601> (or "never")
Errors:       <total_errors>
  - contract.pdf — password_protected (3 days ago)
  - scan_47.pdf — corrupt (3 days ago)
  ... (and 47 more)
  ↳ Showing 50 most recent of 312. Run /index to refresh.
```

Render rules:
- Show the first 5 errors inline as bullet points.
- After the 5th, render `... (and <N-5> more)` if `len(errors) > 5`.
- Render the `Showing 50 most recent of <total_errors>. Run /index to
  refresh.` footer iff `errors_truncated`.
- Relative time (`3 days ago`) is computed from `indexed_at` in the skill,
  not the server. Server returns the raw timestamp.

## Data flow on a fresh status read

1. Plugin calls the resource with the b64-encoded folder path.
2. Shim base64-decodes to a folder path, forwards to daemon
   `folder_status` RPC.
3. Service derives the project name, reads `total_docs` /
   `total_chunks` / `last_indexed_at` via `index_status(limit=1)` (existing
   path), reads errors via `IndexingStore.list_errors(project, limit=50)` and
   total via `count_errors(project)`.
4. Each error row is mapped to a `FolderError` with `category` computed by
   `error_taxonomy.classify(rec.error_message)` and `file_name` set to
   `Path(rec.file_path).name`.
5. `folder_status` returns the dict; resource returns it verbatim.

## PII / leak analysis

- **Raw `error_message` (the persisted SQLite column): never returned.** Only
  `category` (closed enumeration) and `error_class` (Python type name) cross
  the service boundary.
- **`file_name` is the basename only.** No directory components.
- **`file_path` is the full path.** This is acceptable: the user reading
  `/status` already owns this filesystem; there is no privacy boundary
  between them and their own paths. Outbound use of `file_path` (e.g. as
  payload to a non-Anthropic tool) is the redact-outbound skill's
  responsibility, same as it is today for `index_status` (which already
  exposes full paths).
- **No exception class name surfaced.** The Python class name is
  embedded in the persisted `error_message` column but never crosses the
  service boundary — only `category` does.

## Testing

- **Unit / `test_error_taxonomy.py`** — fixtures of real exception messages
  we've observed (kreuzberg encryption errors, openpyxl format errors, pdf
  parse errors, timeout errors), one assertion per category, plus an
  `"other"` fallback test. ~15 fixtures.
- **Unit / `test_indexing_store_errors.py`** — three tests:
  - `list_errors` returns only `status='error'` rows
  - results ordered by `indexed_at DESC`
  - `limit` is honoured; `count_errors` returns the unbounded total
- **Service / `test_service_folder_status_errors.py`** — three tests:
  - empty project → `errors=[], total_errors=0, errors_truncated=False`
  - project with 3 error rows → `total_errors=3, errors_truncated=False`,
    each `FolderError` has the right basename and a category from the
    closed set
  - project with 60 error rows → `len(errors)==50, total_errors==60,
    errors_truncated=True`
- **No skill render test** — markdown formatting is reviewed visually in the
  manual `/status` end-to-end test.

## Files touched

| Path | Type | Change |
|---|---|---|
| `src/piighost/indexer/indexing_store.py` | modified | `list_errors`, `count_errors` |
| `src/piighost/service/error_taxonomy.py` | new | classifier |
| `src/piighost/service/models.py` | modified | `FolderError` |
| `src/piighost/service/core.py` | modified | `folder_status` extension |
| `tests/unit/test_error_taxonomy.py` | new | classifier tests |
| `tests/unit/test_indexing_store_errors.py` | new | store tests |
| `tests/unit/test_service_folder_status_errors.py` | new | service tests |
| `.worktrees/hacienda-plugin/skills/status/SKILL.md` | modified | render |

## Open questions

None at spec time. Implementation may surface category-mapping edge cases
that warrant adding entries to `_TAXONOMY`; that is part of the unit-fixture
loop, not a design decision.

## Risk

- **Schema lock-in on category names.** Once the plugin renders
  `password_protected`, downstream automation (compliance dashboards,
  retry scripts) will treat the strings as a stable enum. The taxonomy
  must be additive-only after first ship — never rename a category, only
  add new ones. Document this in the module docstring.
- **Taxonomy false-negatives.** If the substring matcher fails to recognise
  a real error pattern, it falls back to `"other"`, which is the safe
  outcome (no leak, just less informative). Adding patterns is cheap and
  doesn't break consumers.
