# piighost Sprint 5 — Multi-Project Isolation Design

**Date:** 2026-04-20
**Scope:** Add strict per-project isolation. Each project has its own vault, chunk store, BM25 index, and token namespace. "Alice" in project A gets a completely different token than "Alice" in project B, and rehydrating a project-A token in a project-B context fails explicitly.

---

## Goals

1. Support multiple logical projects within a single `vault_dir`, each with fully independent retrieval and vault state.
2. Token namespacing: identical PII values produce **different** tokens across projects (via salted `HashPlaceholderFactory`).
3. All existing MCP tools gain a `project` parameter; 3 new tools (`list_projects`, `create_project`, `delete_project`).
4. Backward-compatible migration from Sprint 3/4 layout (single-vault) to Sprint 5 layout (per-project subtree) — existing data moves into `projects/default/`.
5. Zero cross-project bleed: queries, vault searches, rehydrations, and statistics are strictly scoped to the project parameter.

## Non-goals

- Cross-project token linking (explicitly rejected — breaks the isolation guarantee).
- Per-user ACLs / multi-tenant auth. Projects are a logical partition, not a security boundary between OS users; anyone with read access to `vault_dir` can read all projects.
- Project-level config overrides (every project inherits the top-level `ServiceConfig`). Deferred to a future sprint.
- UI for project switching in Claude Desktop — projects are passed as tool arguments.

---

## 1. Storage layout

```
${vault_dir}/
├── projects.db                   # NEW: project registry (single SQLite)
└── projects/
    ├── default/                  # fallback project; legacy data migrates here
    │   ├── vault.db
    │   ├── audit.log
    │   └── .piighost/
    │       ├── lance/
    │       └── bm25.pkl
    ├── client-a/
    │   └── ... (same structure)
    └── client-b/
        └── ...
```

Each `${vault_dir}/projects/<name>/` is a self-contained piighost project state — byte-identical in structure to the Sprint 3/4 single-vault layout, just rooted one level deeper.

## 2. Project registry (`projects.db`)

Single SQLite file at `${vault_dir}/projects.db`. Tracks project metadata.

```sql
CREATE TABLE IF NOT EXISTS projects (
    name TEXT PRIMARY KEY,
    description TEXT,
    created_at INTEGER NOT NULL,
    last_accessed_at INTEGER NOT NULL,
    placeholder_salt TEXT NOT NULL DEFAULT ''
);
```

`placeholder_salt` seeds the project's `HashPlaceholderFactory` (section 5 + 9). New projects default to `placeholder_salt = <name>` (set at creation time via `create_project`). The `default` project created by migration uses `placeholder_salt = ''` for backward compatibility with pre-v3 tokens.

Project name validation (applied at every entry point): `re.fullmatch(r"[a-zA-Z0-9_\-]+", name)` — rejects spaces, path separators, `..`, Unicode, emoji. Names are limited to 64 characters to avoid filesystem path issues on Windows.

## 3. Schema v3 migration

One-way, idempotent. Runs during `PIIGhostService.create(vault_dir=...)` before any other initialization.

```python
def _migrate_to_v3(vault_dir: Path) -> None:
    projects_dir = vault_dir / "projects"
    if projects_dir.exists():
        return  # already v3
    legacy_vault = vault_dir / "vault.db"
    projects_dir.mkdir(parents=True, exist_ok=True)
    default_dir = projects_dir / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    if legacy_vault.exists():
        # Move Sprint 1-4 state into projects/default/
        for name in ("vault.db", "audit.log"):
            src = vault_dir / name
            if src.exists():
                src.rename(default_dir / name)
        legacy_piighost = vault_dir / ".piighost"
        if legacy_piighost.exists():
            legacy_piighost.rename(default_dir / ".piighost")
    # Initialize projects.db
    _ensure_project_registry(vault_dir / "projects.db")
    _ensure_project_row("default", description="Migrated from pre-v3 layout")
```

Migration logs a single line to the `default` project's audit log: `{"op": "schema_migration", "from_version": 2, "to_version": 3, "ts": ...}`.

If the migration is interrupted mid-move, the directory state is non-atomic but recoverable: a subsequent run detects the partial state (some files in `projects/default/`, others still at root) and finishes the move.

## 4. Service architecture

Today `PIIGhostService` owns a single `Vault`, `ChunkStore`, `BM25Index`. For Sprint 5 the class becomes a **multiplexer** that lazily creates and caches per-project services.

### 4.1 `_ProjectService`

Rename the current `PIIGhostService` internals to `_ProjectService`. This class becomes private, owns one project's state, and knows nothing about other projects. Every method that existed on `PIIGhostService` (Sprint 1-4) lives here unchanged.

```python
class _ProjectService:
    def __init__(self, project_dir: Path, project_name: str, placeholder_salt: str, config: ServiceConfig, ...):
        self._vault = Vault.open(project_dir / "vault.db")
        self._audit = AuditLogger(project_dir / "audit.log")
        self._chunk_store = ChunkStore(project_dir / ".piighost" / "lance")
        self._bm25 = BM25Index(project_dir / ".piighost" / "bm25.pkl")
        self._bm25.load()
        # Salted factory — salt is read from the project registry (usually project name,
        # but '' for the migrated default project so pre-v3 tokens still rehydrate).
        self._ph = HashPlaceholderFactory(salt=placeholder_salt)
        # ... existing construction logic
```

The multiplexer reads `placeholder_salt` from `projects.db` and passes it to `_ProjectService`. This gives the registry final authority over token isolation — a pre-existing project keeps its original salt even if the multiplexer code is later changed.

### 4.2 `PIIGhostService` (multiplexer)

```python
class PIIGhostService:
    LRU_SIZE = 8

    def __init__(self, vault_dir: Path, config: ServiceConfig, ...):
        self._vault_dir = vault_dir
        self._config = config
        self._registry = ProjectRegistry(vault_dir / "projects.db")
        self._cache: OrderedDict[str, _ProjectService] = OrderedDict()

    @classmethod
    async def create(cls, *, vault_dir: Path, config: ServiceConfig | None = None, ...) -> "PIIGhostService":
        _migrate_to_v3(vault_dir)
        # ... existing setup ...

    async def _get_project(self, name: str, *, auto_create: bool = False) -> _ProjectService:
        _validate_project_name(name)
        if name in self._cache:
            self._cache.move_to_end(name)
            return self._cache[name]
        exists = self._registry.exists(name)
        if not exists:
            if not auto_create:
                raise ProjectNotFound(name)
            self._registry.create(name)
        project_dir = self._vault_dir / "projects" / name
        svc = await _ProjectService.create(project_dir, name, self._config)
        self._cache[name] = svc
        # LRU eviction
        while len(self._cache) > self.LRU_SIZE:
            evicted_name, evicted_svc = self._cache.popitem(last=False)
            await evicted_svc.close()
        self._registry.touch(name)
        return svc
```

Every public method on `PIIGhostService` gains a `project: str` parameter and delegates to `_get_project(...)`. Write-path methods (`anonymize`, `index_path`) pass `auto_create=True`. Read-path methods (`query`, `vault_*`, `rehydrate`, `remove_doc`, `index_status`) pass `auto_create=False` and surface `ProjectNotFound` to the caller.

### 4.3 Multiplexer methods

```python
async def list_projects(self) -> list[ProjectInfo]: ...
async def create_project(self, name: str, description: str = "") -> ProjectInfo: ...
async def delete_project(self, name: str, *, force: bool = False) -> bool: ...
```

`delete_project` refuses if the project still has indexed files or vault entries unless `force=True`. `delete_project("default")` is always refused — the default project is permanent.

## 5. Token namespacing via salted factory

`HashPlaceholderFactory` currently hashes entity text + label → token. It gains a `salt` constructor parameter:

```python
class HashPlaceholderFactory:
    def __init__(self, salt: str = "") -> None:
        self._salt = salt.encode("utf-8")

    def create(self, entities: list[Entity]) -> dict[Entity, str]:
        out = {}
        for ent in entities:
            h = hashlib.sha256()
            h.update(self._salt)
            h.update(b"\x00")
            h.update(ent.label.encode("utf-8"))
            h.update(b"\x00")
            h.update(ent.text.encode("utf-8"))
            digest = h.hexdigest()[:8]
            out[ent] = f"<{ent.label}:{digest}>"
        return out
```

Each `_ProjectService` passes its project name as the salt. Identical entities produce identical tokens within a project and different tokens across projects.

**Breaking change note:** token format is unchanged (`<LABEL:8hex>`), but token *values* for the default project will differ after migration (because the salt was empty before and becomes `"default"` after). Existing documents anonymized pre-v3 **cannot be rehydrated post-v3 without a compatibility path**. See section 9 for the mitigation.

## 6. MCP tool surface

All existing tools gain a `project` parameter. Three new tools for project management.

### 6.1 Updated signatures

```python
# Anonymization / detection
anonymize_text(text: str, doc_id: str = "", project: str = "default") -> dict
rehydrate_text(text: str, project: str = "default") -> dict
detect(text: str) -> list[dict]   # unchanged — stateless

# Indexing / retrieval
index_path(path: str, recursive: bool = True, force: bool = False, project: str | None = None) -> dict
query(text: str, k: int = 5, project: str = "default") -> dict
remove_doc(path: str, project: str = "default") -> dict
index_status(limit: int = 100, offset: int = 0, project: str = "default") -> dict

# Vault
vault_search(q: str, reveal: bool = False, project: str = "default") -> list[dict]
vault_list(label: str = "", limit: int = 100, offset: int = 0, reveal: bool = False, project: str = "default") -> list[dict]
vault_get(token: str, reveal: bool = False, project: str = "default") -> dict | None
vault_stats(project: str = "default") -> dict
```

### 6.2 New tools

```python
list_projects() -> list[dict]
    # [{"name": ..., "description": ..., "created_at": ..., "last_accessed_at": ..., "doc_count": ..., "vault_entity_count": ...}]

create_project(name: str, description: str = "") -> dict
    # {"name": ..., "description": ..., "created_at": ...}

delete_project(name: str, force: bool = False) -> dict
    # {"deleted": True, "name": ...}  OR  ProjectNotFound / ProjectNotEmpty error
```

### 6.3 Auto-derivation for `index_path`

When `index_path(path, project=None)` is called, derive the project name from the path:

```python
_GENERIC_NAMES = {"documents", "desktop", "downloads", "src", "tmp", "home", "users", "projects"}

def _derive_project(path: Path) -> str:
    parts = [p for p in path.resolve().parts if p.strip("/")]
    for part in reversed(parts[:-1]):  # skip the deepest component (it's usually the folder being indexed)
        if part.lower() not in _GENERIC_NAMES and re.fullmatch(r"[a-zA-Z0-9_\-]+", part):
            return part
    return "default"
```

The response always includes the resolved `project` field so Claude can report which project received the content.

### 6.4 MCP resources

- `piighost://vault/stats` → aggregate summary across all projects (total entity count, per-project counts)
- `piighost://projects` → NEW, JSON list of all projects
- `piighost://projects/{name}/stats` → NEW, per-project stats

## 7. CLI surface

Every indexing/vault command gains `--project <name>`. No auto-derivation at CLI level — explicit.

```bash
piighost anonymize --project client-a "Alice lives in Paris."
piighost index --project client-a ./contracts
piighost query --project client-a "GDPR compliance"
piighost vault list --project client-a --reveal
piighost rm --project client-a ./contracts/draft.pdf
piighost index-status --project client-a

# New subcommands
piighost projects list
piighost projects create <name> [--description ...]
piighost projects delete <name> [--force]
```

Default value for `--project` in CLI: if the user's current directory is inside a project-like path, derive from that; otherwise default to `"default"`. Matches Sprint 5 `index_path` auto-derivation behavior.

## 8. Daemon dispatch

Every RPC method that accepts a project parameter forwards it from the JSON body. New methods `list_projects`, `create_project`, `delete_project` added to the dispatch table.

## 9. Migration of pre-v3 tokens

Tokens anonymized with the old (unsalted) factory do not match what the salted factory produces. Rehydration of pre-v3 anonymized documents would fail silently after migration.

**Mitigation**: the salted factory's behavior is controlled by the per-project `placeholder_salt` field stored in the project registry (defined in section 2). For the `default` project created by migration, `placeholder_salt = ""` (empty — matches legacy behavior). For all projects created after v3 via `create_project(name)`, `placeholder_salt` defaults to the project name.

The multiplexer reads this field from the registry and passes it to `HashPlaceholderFactory(salt=...)` when constructing `_ProjectService`. Users with pre-v3 tokens can continue to rehydrate in the `default` project indefinitely. New projects get the stronger isolation guarantee.

The `create_project(name)` tool defaults `placeholder_salt` to the project name. Callers may override via `create_project(name, placeholder_salt="custom")` if they need cross-project token sharing for a specific use case — but the default is strict isolation.

## 10. Error handling

| Case | Response |
|------|----------|
| Invalid project name (whitespace, traversal, Unicode, `>64` chars) | `ValueError("invalid project name: ...")` at service layer, surfaced as MCP tool error |
| `query` / `vault_*` / `remove_doc` / `index_status` / `rehydrate` on a project that doesn't exist | `ProjectNotFound("project '<name>' does not exist; call list_projects to see available projects")` |
| `anonymize` / `index_path` on a non-existent project | Auto-create, return successful response with `project` field populated |
| `rehydrate_text` token unknown in project's vault | `RehydrationError("token <X> unknown in project '<name>'")` in strict mode (default); `unknown_tokens` in the response in lenient mode |
| `delete_project("default")` | `ValueError("the default project cannot be deleted")` |
| `delete_project(name)` where the project has indexed files or vault entries | `ProjectNotEmpty("project '<name>' contains N docs and M vault entries; pass force=True to delete anyway")` |
| Concurrent `index_path` on same project | Existing per-project `_write_lock` serializes writes; no cross-project contention |
| Two concurrent calls for different projects | Multiplexer dict access is thread-safe (CPython GIL); `_get_project` is an `async` coroutine and uses `await` points cleanly |

## 11. PII safety invariants (preserved + strengthened)

- **Strengthened**: different projects produce different tokens for the same entity. Cross-project token leakage is impossible by construction.
- **Strengthened**: `rehydrate_text` failure explicitly names the project context (no silent cross-project lookup).
- Preserved: no raw PII in error messages; validator exceptions are caught; `type(exc).__name__` is used in error strings.
- Preserved: MCP `reveal=True` writes an audit entry; audit log is per-project so you get project-scoped audit trails.

## 12. Testing

| Layer | Tests |
|-------|-------|
| `ProjectRegistry` unit | `tests/unit/test_project_registry.py` — CRUD, name validation, timestamp updates |
| Schema v3 migration | `tests/unit/test_schema_v3_migration.py` — simulated v2 layout → verify moves, `default` row created, idempotency (second run is a no-op) |
| Multiplexer cache | `tests/unit/test_service_multiplexer.py` — LRU eviction closes evicted services, concurrent async access doesn't corrupt cache |
| Auto-derivation | `tests/unit/test_project_derivation.py` — `/Users/x/projects/client-a/docs/` → `client-a`; `/tmp/` → `default`; generic names skipped; invalid chars fallback to `default` |
| Tool wiring | `tests/unit/test_mcp_project_wiring.py` — all tools dispatch to correct project; missing project triggers correct auto-create or `ProjectNotFound` |
| Salted placeholder factory | `tests/unit/test_salted_placeholder.py` — same entity + different salt → different token; empty salt matches legacy behavior |
| **Token isolation (critical)** | `tests/e2e/test_project_isolation.py` — `test_tokens_differ_across_projects`, `test_rehydrate_fails_in_wrong_project`, `test_query_scoped_to_project`, `test_vault_search_scoped_to_project` |
| Migration E2E | `tests/e2e/test_v2_to_v3_migration.py` — build a v2 vault with Sprint 3 test fixtures, create a v3 service pointing at it, verify all pre-v3 data accessible under `default` project |
| CLI project flag | `tests/unit/test_cli_project_flag.py` — `--project` flag threads through every command |

### The critical isolation test

```python
def test_tokens_differ_across_projects(svc, tmp_path):
    a = asyncio.run(svc.anonymize("Alice works here", project="client-a"))
    b = asyncio.run(svc.anonymize("Alice works here", project="client-b"))
    a_token = a.entities[0].token
    b_token = b.entities[0].token
    assert a_token != b_token

def test_rehydrate_fails_in_wrong_project(svc):
    r = asyncio.run(svc.anonymize("Alice works here", project="client-a"))
    # Token is recorded in client-a's vault. Rehydrating in client-b must fail.
    rehydrated = asyncio.run(svc.rehydrate(r.anonymized, project="client-b"))
    assert r.entities[0].token in rehydrated.unknown_tokens
    assert "Alice" not in rehydrated.text
```

## 13. Acceptance criteria

- Existing Sprint 3/4 vault state migrates transparently to `projects/default/` on first Sprint 5 launch — zero user action required.
- `piighost query --project client-a` returns only client-a docs; `piighost vault list --project client-a` returns only client-a entities.
- `piighost anonymize --project client-a "Alice"` and `piighost anonymize --project client-b "Alice"` produce different tokens.
- `rehydrate` in project B of a token minted in project A returns the token in `unknown_tokens` (strict mode raises).
- `list_projects` returns all projects; each includes `doc_count` and `vault_entity_count`.
- `delete_project("default")` always fails with a clear error.
- `delete_project(name)` on a non-empty project fails unless `force=True`.
- MCP resource `piighost://projects` lists all projects.
- All 178+ existing tests continue to pass (after they're updated to pass `project="default"` where needed, OR the `project="default"` default applies and they keep working).

## 14. Out of scope

- Project renaming (add in Sprint 5.1 if demand emerges — requires updating `indexed_files.doc_id` references and re-salting tokens, non-trivial).
- Project export/import (dump a project as a portable archive).
- Per-project config overrides (e.g., different detector backend per project).
- Access control / user-level permissions on projects.
- Cross-project token linking ("alias these tokens across projects"). Explicitly rejected — breaks the isolation guarantee that's the whole point of Sprint 5.
- UI picker in Claude Desktop for current project. Projects are passed per-call.
