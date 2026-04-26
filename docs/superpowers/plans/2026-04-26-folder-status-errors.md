# folder_status errors[] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface persisted file-level indexing errors through `folder_status` and the `piighost://folders/{b64}/status` MCP resource, so the hacienda plugin's `/status` command can report *"3 files failed: contract.pdf — password_protected, scan.pdf — corrupt, …"*.

**Architecture:** The data already lives in `indexed_files` (SQLite, `status='error'` rows with `error_message`, `indexed_at`, `file_path`). This plan plumbs it through a new query method on `IndexingStore`, a pure sanitisation taxonomy (`error_taxonomy.classify`), a new `FolderError` pydantic model, and three additive fields on `folder_status`. Raw exception text never crosses the service boundary; only a bounded category enum (`password_protected | corrupt | unsupported_format | timeout | other`) is exposed.

**Tech Stack:** Python 3.13, SQLite (stdlib), pydantic, pytest. Same stack as the rest of `piighost`.

**Spec:** `docs/superpowers/specs/2026-04-26-folder-status-errors-design.md` (commit `51b581a`).

**Project root for all paths below:** `C:\Users\NMarchitecte\Documents\piighost`. The hacienda plugin lives in the worktree `.worktrees/hacienda-plugin/` (separate git repo, `jamon8888/hacienda` `main`).

---

## File map

| Path | Type | Owns |
|---|---|---|
| `src/piighost/service/error_taxonomy.py` | new | Pure classifier mapping persisted `error_message` to bounded category |
| `tests/unit/test_error_taxonomy.py` | new | ~15 fixtures across all 5 categories + fallback |
| `src/piighost/indexer/indexing_store.py` | modify | Add `list_errors` + `count_errors` methods |
| `tests/unit/test_indexing_store_errors.py` | new | Status filter, ordering, limit, count |
| `src/piighost/service/models.py` | modify | Add `FolderError` pydantic model |
| `src/piighost/service/core.py` | modify | Extend `folder_status` return shape |
| `tests/unit/test_service_folder_status_errors.py` | new | Empty / 3 errors / 60 errors (truncation) |
| `.worktrees/hacienda-plugin/skills/status/SKILL.md` | modify | Render errors with truncation hint |

Tasks 1 → 4 are all in the main `piighost` repo and produce a working server-side feature on their own. Task 5 lives in the plugin worktree (separate repo).

---

## Task 1: Error taxonomy module + tests

**Files:**
- Create: `src/piighost/service/error_taxonomy.py`
- Test: `tests/unit/test_error_taxonomy.py`

This is a pure function with no external dependencies — start here so later tasks can depend on it.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_error_taxonomy.py`:

```python
"""Tests for the error_taxonomy.classify() function — maps persisted
error_message strings to a bounded category enum, never returning the
raw input."""
from __future__ import annotations

import pytest

from piighost.service.error_taxonomy import classify


@pytest.mark.parametrize("msg", [
    "KreuzbergError: file is password-protected",
    "ValueError: PDF is encrypted; provide a password",
    "PdfReadError: could not decrypt /clients/foo/contract.pdf",
])
def test_password_protected(msg):
    assert classify(msg) == "password_protected"


@pytest.mark.parametrize("msg", [
    "ExtractionError: file is corrupt",
    "PdfReadError: invalid PDF header",
    "ValueError: malformed XLSX",
])
def test_corrupt(msg):
    assert classify(msg) == "corrupt"


@pytest.mark.parametrize("msg", [
    "ExtractionError: unsupported file type .heic",
    "RuntimeError: no extractor registered for .key",
    "TypeError: format not supported",
])
def test_unsupported_format(msg):
    assert classify(msg) == "unsupported_format"


@pytest.mark.parametrize("msg", [
    "TimeoutError: extraction timeout after 60s",
    "asyncio.TimeoutError: timed out",
])
def test_timeout(msg):
    assert classify(msg) == "timeout"


@pytest.mark.parametrize("msg", [
    "RuntimeError: something weird happened",
    "ValueError: unknown",
    "",
])
def test_other_fallback(msg):
    assert classify(msg) == "other"


def test_none_input_returns_other():
    assert classify(None) == "other"


def test_classify_is_case_insensitive():
    assert classify("ERROR: PASSWORD-PROTECTED FILE") == "password_protected"


def test_classify_never_returns_input():
    """Spec invariant: raw input must not appear in the output."""
    secret = "ExtractionError: failed on /clients/Martin Dupont/contract.pdf"
    out = classify(secret)
    assert "Martin Dupont" not in out
    assert "/clients" not in out
    assert out == "other"  # path-only message has no taxonomy keyword
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `C:\Users\NMarchitecte\Documents\piighost`:
```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_error_taxonomy.py -v --no-header
```
Expected: ImportError on `piighost.service.error_taxonomy` (module does not exist).

- [ ] **Step 3: Implement the module**

Create `src/piighost/service/error_taxonomy.py`:

```python
"""Map raw indexer ``error_message`` strings to a bounded category enum.

The ``indexed_files`` table stores ``error_message`` as
``f"{type(exc).__name__}: {exc}"``. Raw exception text can contain file
paths or document fragments that are PII, so the service boundary
exposes only the bounded category returned by :func:`classify`.

Category vocabulary (additive-only, never rename):

- ``password_protected`` — file requires a credential to open
- ``corrupt``            — file structure is invalid / unreadable
- ``unsupported_format`` — extension or signature has no extractor
- ``timeout``            — extraction exceeded its time budget
- ``other``              — anything else, including ``None`` / empty input
"""
from __future__ import annotations

# Order matters: first match wins. Keep most specific patterns first.
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
    """Return the bounded category for ``error_message``.

    Matches case-insensitively against substrings in ``_TAXONOMY`` in
    declaration order; first match wins. Returns ``"other"`` for
    unrecognised messages, the empty string, and ``None``.

    Never returns the input string directly — this is a hard invariant
    enforced by tests.
    """
    if not error_message:
        return "other"
    haystack = error_message.lower()
    for needle, category in _TAXONOMY:
        if needle in haystack:
            return category
    return "other"
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_error_taxonomy.py -v --no-header
```
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/error_taxonomy.py tests/unit/test_error_taxonomy.py
git commit -m "feat(service): error_taxonomy.classify() pure mapper

Maps persisted error_message strings to a bounded category enum
(password_protected | corrupt | unsupported_format | timeout | other).
Raw input is never returned — closed enumeration prevents PII fragments
in error messages from leaking through folder_status.

Part of folder_status errors[] feature
(spec: 2026-04-26-folder-status-errors-design.md)."
```

---

## Task 2: IndexingStore.list_errors + count_errors + tests

**Files:**
- Modify: `src/piighost/indexer/indexing_store.py` (add two methods to `IndexingStore` class)
- Test: `tests/unit/test_indexing_store_errors.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_indexing_store_errors.py`:

```python
"""Tests for IndexingStore.list_errors and count_errors."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from piighost.indexer.indexing_store import FileRecord, IndexingStore


def _record(
    *, project: str, path: str, status: str, indexed_at: float,
    error_message: str | None = None,
) -> FileRecord:
    return FileRecord(
        project_id=project,
        file_path=path,
        file_mtime=0.0,
        file_size=0,
        content_hash="",
        indexed_at=indexed_at,
        status=status,
        error_message=error_message,
        entity_count=None,
        chunk_count=None,
    )


@pytest.fixture()
def store(tmp_path):
    s = IndexingStore.open(tmp_path / "indexing.sqlite")
    yield s
    s.close()


def test_list_errors_returns_only_error_status(store):
    store.upsert(_record(project="p", path="/a.pdf", status="success",
                         indexed_at=100.0))
    store.upsert(_record(project="p", path="/b.pdf", status="error",
                         indexed_at=101.0,
                         error_message="ExtractionError: corrupt"))
    store.upsert(_record(project="p", path="/c.pdf", status="deleted",
                         indexed_at=102.0))

    errs = store.list_errors("p")
    assert len(errs) == 1
    assert errs[0].file_path == "/b.pdf"
    assert errs[0].status == "error"


def test_list_errors_orders_by_indexed_at_desc(store):
    store.upsert(_record(project="p", path="/old.pdf", status="error",
                         indexed_at=100.0,
                         error_message="ExtractionError: corrupt"))
    store.upsert(_record(project="p", path="/new.pdf", status="error",
                         indexed_at=200.0,
                         error_message="ExtractionError: corrupt"))
    store.upsert(_record(project="p", path="/mid.pdf", status="error",
                         indexed_at=150.0,
                         error_message="ExtractionError: corrupt"))

    errs = store.list_errors("p")
    assert [r.file_path for r in errs] == ["/new.pdf", "/mid.pdf", "/old.pdf"]


def test_list_errors_honours_limit_and_count_returns_total(store):
    for i in range(60):
        store.upsert(_record(
            project="p", path=f"/f{i}.pdf", status="error",
            indexed_at=float(i),
            error_message="ExtractionError: corrupt",
        ))

    errs = store.list_errors("p", limit=50)
    assert len(errs) == 50
    # Newest first → /f59.pdf is the first row
    assert errs[0].file_path == "/f59.pdf"
    assert store.count_errors("p") == 60


def test_list_errors_isolates_by_project(store):
    store.upsert(_record(project="p", path="/a.pdf", status="error",
                         indexed_at=100.0,
                         error_message="ExtractionError: corrupt"))
    store.upsert(_record(project="q", path="/a.pdf", status="error",
                         indexed_at=101.0,
                         error_message="ExtractionError: corrupt"))

    assert len(store.list_errors("p")) == 1
    assert len(store.list_errors("q")) == 1
    assert store.count_errors("p") == 1
    assert store.count_errors("q") == 1


def test_count_errors_returns_zero_for_unknown_project(store):
    assert store.count_errors("does-not-exist") == 0
    assert store.list_errors("does-not-exist") == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_indexing_store_errors.py -v --no-header
```
Expected: AttributeError on `store.list_errors` and `store.count_errors`.

- [ ] **Step 3: Implement the methods**

Open `src/piighost/indexer/indexing_store.py`. Find the `mark_deleted` method (around line 177-182) and add the two new methods immediately after it, before the `batch()` method:

```python
    def list_errors(
        self,
        project_id: str,
        *,
        limit: int = 50,
    ) -> list[FileRecord]:
        """Return up to ``limit`` most-recent ``status='error'`` rows for
        ``project_id``, ordered by ``indexed_at`` DESC.

        The ``(project_id, status)`` index covers the predicate; the
        ``ORDER BY indexed_at DESC LIMIT N`` clause is satisfied by a
        small in-memory sort, which is fine at the limits we care about
        (default 50, never more than a few hundred in practice)."""
        cur = self._conn.execute(
            "SELECT * FROM indexed_files "
            "WHERE project_id = ? AND status = 'error' "
            "ORDER BY indexed_at DESC "
            "LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_record(row) for row in cur.fetchall()]

    def count_errors(self, project_id: str) -> int:
        """Return the total number of ``status='error'`` rows for
        ``project_id``, ignoring any limit. Used as the truncation
        indicator for :meth:`list_errors`."""
        cur = self._conn.execute(
            "SELECT COUNT(*) AS n FROM indexed_files "
            "WHERE project_id = ? AND status = 'error'",
            (project_id,),
        )
        row = cur.fetchone()
        return int(row["n"]) if row else 0
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_indexing_store_errors.py -v --no-header
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/indexer/indexing_store.py tests/unit/test_indexing_store_errors.py
git commit -m "feat(indexing_store): list_errors + count_errors

Two new query methods on IndexingStore that surface persisted
status='error' rows. list_errors returns at most limit rows ordered
by indexed_at DESC; count_errors returns the unbounded total for
the truncation indicator.

The (project_id, status) SQLite index already covers the predicate.

Part of folder_status errors[] feature."
```

---

## Task 3: FolderError pydantic model

**Files:**
- Modify: `src/piighost/service/models.py` (append a new model)

This is a tiny task on its own, but isolating it as one commit makes the diff readable and lets Task 4's diff stay focused on `folder_status` semantics.

- [ ] **Step 1: Add the model**

Open `src/piighost/service/models.py`. After the last model in the file (currently `CancelResult` ending around line 113), append:

```python


class FolderError(BaseModel):
    """One file-level indexing failure surfaced by ``folder_status``.

    The Python exception class name is intentionally not exposed —
    server logs are the source of truth for individual exceptions.
    Only the bounded ``category`` (one of ``password_protected``,
    ``corrupt``, ``unsupported_format``, ``timeout``, ``other``)
    crosses the service boundary."""

    file_name: str        # basename only — safe for outbound rendering
    file_path: str        # full path — already exposed by index_status
    category: str         # one of the error_taxonomy values
    indexed_at: int       # unix epoch seconds
```

- [ ] **Step 2: Smoke-test the import**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "from piighost.service.models import FolderError; print(FolderError(file_name='a.pdf', file_path='/a.pdf', category='corrupt', indexed_at=1730000000))"
```
Expected: prints a `FolderError` instance with the four fields.

- [ ] **Step 3: Commit**

```bash
git add src/piighost/service/models.py
git commit -m "feat(models): FolderError pydantic record

One file-level indexing failure as surfaced by folder_status.
Bounded category enum; no Python exception class name exposed."
```

---

## Task 4: Extend folder_status return shape + tests

**Files:**
- Modify: `src/piighost/service/core.py` (the existing `folder_status` method)
- Test: `tests/unit/test_service_folder_status_errors.py`

This is the integration task that wires Tasks 1-3 into the public API.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_service_folder_status_errors.py`:

```python
"""Tests for the new errors[] / errors_truncated / total_errors fields
on PIIGhostService.folder_status. The 'state' / 'total_docs' /
'last_indexed_at' fields are covered by test_service_hacienda_rpcs.py."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.indexer.indexing_store import FileRecord
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir))


def _seed_error_row(svc, project: str, *, path: str, when: float, msg: str) -> None:
    """Reach into the project's IndexingStore and write one error row.
    Bypasses index_path so the test does not depend on extractor stack."""
    proj = asyncio.run(svc._get_project(project, auto_create=True))
    proj._indexing_store.upsert(FileRecord(
        project_id=project,
        file_path=path,
        file_mtime=0.0,
        file_size=0,
        content_hash="",
        indexed_at=when,
        status="error",
        error_message=msg,
        entity_count=None,
        chunk_count=None,
    ))


def test_folder_status_empty_project_returns_no_errors(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client-empty"
    folder.mkdir()

    status = asyncio.run(svc.folder_status(folder))
    assert status["errors"] == []
    assert status["errors_truncated"] is False
    assert status["total_errors"] == 0
    asyncio.run(svc.close())


def test_folder_status_returns_categorised_errors(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client-three"
    folder.mkdir()

    # Bootstrap so the project exists, then seed 3 error rows directly.
    boot = asyncio.run(svc.bootstrap_client_folder(folder))
    project = boot["project"]
    _seed_error_row(svc, project, path=str(folder / "a.pdf"),
                    when=300.0, msg="ExtractionError: file is password-protected")
    _seed_error_row(svc, project, path=str(folder / "b.pdf"),
                    when=200.0, msg="ExtractionError: file is corrupt")
    _seed_error_row(svc, project, path=str(folder / "c.heic"),
                    when=100.0, msg="ExtractionError: unsupported file type")

    status = asyncio.run(svc.folder_status(folder))
    assert status["total_errors"] == 3
    assert status["errors_truncated"] is False
    assert len(status["errors"]) == 3

    # Newest first
    cats = [e["category"] for e in status["errors"]]
    assert cats == ["password_protected", "corrupt", "unsupported_format"]

    # Sanitisation: file_name is basename only
    names = [e["file_name"] for e in status["errors"]]
    assert names == ["a.pdf", "b.pdf", "c.heic"]
    # No raw error message appears in any field
    for e in status["errors"]:
        assert "password-protected" not in e["category"]
        assert "ExtractionError" not in e["category"]
    asyncio.run(svc.close())


def test_folder_status_truncates_at_50(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client-many"
    folder.mkdir()

    boot = asyncio.run(svc.bootstrap_client_folder(folder))
    project = boot["project"]
    for i in range(60):
        _seed_error_row(svc, project, path=str(folder / f"f{i}.pdf"),
                        when=float(i),
                        msg="ExtractionError: file is corrupt")

    status = asyncio.run(svc.folder_status(folder))
    assert status["total_errors"] == 60
    assert status["errors_truncated"] is True
    assert len(status["errors"]) == 50
    # Newest first → f59 is at index 0
    assert status["errors"][0]["file_name"] == "f59.pdf"
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_folder_status_errors.py -v --no-header
```
Expected: KeyError on `"errors"` / `"errors_truncated"` / `"total_errors"` (the dict folder_status returns today doesn't have those fields).

- [ ] **Step 3: Modify `folder_status` to include the new fields**

Open `src/piighost/service/core.py`. Find the `folder_status` method (currently at lines 801-836). Replace its body so it adds three fields to the return dict:

```python
    async def folder_status(self, folder: str | Path) -> dict:
        """Lightweight read-only status of the project that ``folder``
        maps to. Used by the ``piighost://folders/{b64}/status``
        resource to power the plugin's polling. Returns:

            {"folder", "project", "state", "total_docs", "total_chunks",
             "last_indexed_at", "errors", "errors_truncated",
             "total_errors"}

        ``state`` is ``"empty"`` when no docs are indexed,
        ``"indexed"`` otherwise. ``errors`` is up to 50 most-recent
        per-file failures (status='error' rows from the indexing
        store), each sanitised to a bounded category. Future work:
        track in-flight ``index_path`` calls and report ``"indexing"``
        with progress.
        """
        from piighost.service.project_path import derive_project_from_path
        from piighost.service.error_taxonomy import classify
        path = Path(folder).expanduser().resolve()
        project_name = derive_project_from_path(path)
        info = self._registry.get(project_name)
        if info is None:
            return {
                "folder": str(path),
                "project": project_name,
                "state": "empty",
                "total_docs": 0,
                "total_chunks": 0,
                "last_indexed_at": None,
                "errors": [],
                "errors_truncated": False,
                "total_errors": 0,
            }
        svc = await self._get_project(project_name, auto_create=False)
        status = await svc.index_status(limit=1)
        last = status.files[0].indexed_at if status.files else None
        error_rows = svc._indexing_store.list_errors(project_name, limit=50)
        total_errors = svc._indexing_store.count_errors(project_name)
        errors = [
            {
                "file_name": Path(r.file_path).name,
                "file_path": r.file_path,
                "category": classify(r.error_message),
                "indexed_at": int(r.indexed_at),
            }
            for r in error_rows
        ]
        return {
            "folder": str(path),
            "project": project_name,
            "state": "indexed" if status.total_docs > 0 else "empty",
            "total_docs": status.total_docs,
            "total_chunks": status.total_chunks,
            "last_indexed_at": last,
            "errors": errors,
            "errors_truncated": total_errors > len(errors),
            "total_errors": total_errors,
        }
```

Notes on the implementation:
- `svc._indexing_store` is the `_ProjectService`'s store handle. It's a private attr; we're inside the same package, this is the same access pattern used by the rest of `PIIGhostService`.
- The dict-of-dicts return shape (rather than `[FolderError(...).model_dump() for r in error_rows]`) matches the existing `folder_status` style — every other field is a primitive too.
- The `state == "empty"` branch retains the existing behaviour: no project means no errors. When the project exists but `total_docs == 0` (e.g. a freshly-bootstrapped folder), `state` is still `"empty"` but `errors` may be non-empty if files failed mid-index — which is desirable.

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_folder_status_errors.py -v --no-header
```
Expected: 3 passed.

- [ ] **Step 5: Verify the existing folder_status test still passes**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_hacienda_rpcs.py -v --no-header -k "not folder_status_empty_then_indexed"
```
Expected: 4 passed (same as before — the new fields are additive and don't break the existing assertions).

- [ ] **Step 6: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_service_folder_status_errors.py
git commit -m "feat(folder_status): expose persisted file-level errors

Adds three additive fields to folder_status:
  - errors: list[dict] — up to 50 most-recent failures, each with
    file_name (basename), file_path, category (bounded enum),
    indexed_at (epoch seconds).
  - errors_truncated: bool — True iff total_errors > len(errors).
  - total_errors: int — full count regardless of limit.

Raw exception text never crosses the service boundary; only the
category from error_taxonomy.classify() does. The /status slash
command can now render 'contract.pdf — password_protected' for
files that failed at last index, instead of silently hiding them.

Closes part 5 of folder_status errors[] spec
(2026-04-26-folder-status-errors-design.md)."
```

---

## Task 5: Update the /status skill in the hacienda plugin

**Files:**
- Modify: `.worktrees/hacienda-plugin/skills/status/SKILL.md`

This task is in a separate git repo (the plugin worktree). The previous commit (`efdf4ea` on `jamon8888/hacienda` `main`) removed the `Errors` row when we adapted the plugin to the server contract. This task adds it back, now that the server actually returns the data.

- [ ] **Step 1: Read the current SKILL.md to confirm starting state**

```
cat .worktrees/hacienda-plugin/skills/status/SKILL.md
```

The "Render" code block should contain `State`, `Indexed docs`, `Chunks`, `Last update` — but no `Errors` row.

- [ ] **Step 2: Replace the render section**

Open `.worktrees/hacienda-plugin/skills/status/SKILL.md`. Find the "Render" workflow step (currently step 3 with the code block showing `Folder:`, `Project:`, `State:`, etc.). Replace the render block + the lines that follow it with:

```markdown
3. Render:

```
Folder:       <absolute path>
Project:      <project hash>
State:        <indexed|empty>
Indexed docs: <total_docs>
Chunks:       <total_chunks>
Last update:  <last_indexed_at ISO 8601> (or "never" when null)
Errors:       <total_errors>
  - <errors[0].file_name> — <errors[0].category> (<relative time from indexed_at>)
  - <errors[1].file_name> — <errors[1].category> (<relative time>)
  ... up to 5 lines, then "(and <total_errors - 5> more)" if applicable
  ↳ Showing 50 most recent of <total_errors>. Run /index to refresh.
```

Render rules for the Errors block:
- Show the first 5 entries from `errors` as bullet points.
- After 5 entries, if `len(errors) > 5`, append `... (and <len(errors) - 5> more)`.
- If `errors_truncated` is true, append the `↳ Showing 50 most recent of <total_errors>. Run /index to refresh.` footer line.
- If `total_errors == 0`, omit the bullet list entirely (just show `Errors: 0`).
- Compute the relative time (`3 days ago`) from `indexed_at` (unix epoch seconds) in the skill — the server returns the raw integer.
- The `category` value is one of: `password_protected`, `corrupt`, `unsupported_format`, `timeout`, `other`.

4. If `state == "empty"` and `total_errors == 0`, suggest `/index` to the user.
5. If `state == "empty"` and `total_errors > 0`, surface the errors and suggest `/index full` to retry the failed files (after the user has fixed whatever caused them).
6. If `last_indexed_at` is older than 10 minutes on a network drive, suggest `/index incremental`.
```

(Replace the whole numbered list from step 3 onwards. The "Per-file error reporting is not exposed by the v0 status resource…" parenthetical at the end can be deleted entirely — it's no longer accurate.)

- [ ] **Step 3: Verify no stale references remain**

```
grep -n "v0 status resource\|not exposed" .worktrees/hacienda-plugin/skills/status/SKILL.md
```
Expected: no matches.

- [ ] **Step 4: Commit in the plugin worktree**

```bash
cd .worktrees/hacienda-plugin
git add skills/status/SKILL.md
git commit -m "feat(skill/status): render persisted file-level errors

The piighost server now exposes errors[] / errors_truncated /
total_errors on folder_status (piighost main commit forthcoming).
This skill renders them with truncation hints and a retry suggestion
when state='empty' but errors exist."
git push origin main
cd ../..
```

---

## Self-review checklist

Run after writing the plan, before handing off.

**1. Spec coverage:**

| Spec section | Implementing task |
|---|---|
| Components → IndexingStore.list_errors / count_errors | Task 2 |
| Components → error_taxonomy.classify | Task 1 |
| Components → FolderError pydantic | Task 3 |
| Components → folder_status return shape | Task 4 |
| Components → MCP resource | Task 4 (no code change — resource forwards verbatim) |
| Components → /status skill render | Task 5 |
| Testing → test_error_taxonomy.py | Task 1 |
| Testing → test_indexing_store_errors.py | Task 2 |
| Testing → test_service_folder_status_errors.py | Task 4 |
| Out of scope → IndexReport.errors unchanged | not implemented (correct) |
| Out of scope → no retry/clear command | not implemented (correct) |

✓ Every in-scope spec item has a task. No gaps.

**2. Placeholder scan:** No "TBD", "implement later", "add error handling", "similar to". Every code step shows actual code. ✓

**3. Type consistency:**
- `classify(error_message: str | None) -> str` — Task 1 signature, called the same way in Task 4. ✓
- `FolderError` fields `file_name, file_path, category, indexed_at` — Task 3 definition, consumed in Task 4 (as dict literal, not the model — documented in the implementation note). ✓
- `list_errors(project_id, *, limit=50)` and `count_errors(project_id)` — Task 2 signatures, called identically in Task 4. ✓
- `errors_truncated: bool`, `total_errors: int`, `errors: list[dict]` — Task 4 return shape, consumed in Task 5 render. ✓

No type/name mismatches.
