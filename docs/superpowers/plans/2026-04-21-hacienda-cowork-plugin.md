# Hacienda — Claude Desktop Cowork Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Claude Desktop Cowork plugin, `hacienda`, that gives regulated professionals PII-safe RAG over their client folders by wrapping the piighost MCP server — installable from the Anthropic Cowork marketplace with zero CLI steps.

**Architecture:** Pure Cowork plugin (no plugin-side Python). The plugin is configuration + skill prose + a `.mcp.json` that declares the piighost MCP server. All logic — indexing, redaction, rehydration, search, auditing, bootstrap — lives inside the piighost MCP server as tools and resources. Skills invoke those tools; the plugin directory ships no executable code.

**Tech stack:** piighost (Python/FastMCP, existing), Claude Desktop Cowork plugin contract, stdio MCP transport, JSON + Markdown for plugin assets.

---

## Architecture Override — Supersedes Spec §5

The approved spec (`docs/superpowers/specs/2026-04-21-hacienda-cowork-plugin-design.md`) §5 describes a plugin with `hooks/`, `commands/`, `agents/`, `monitors/`, `bin/`, and `vendor/` directories. **That shape is wrong for Cowork.**

Verified against the authoritative reference `anthropics/knowledge-work-plugins` (fetched 2026-04-21, inspecting the `legal/` plugin — closest persona match):

```
legal/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json
├── CONNECTORS.md
├── LICENSE
├── README.md
└── skills/
    ├── brief/SKILL.md
    ├── compliance-check/SKILL.md
    ├── legal-response/SKILL.md
    ├── legal-risk-assessment/SKILL.md
    ├── meeting-briefing/SKILL.md
    ├── review-contract/SKILL.md
    ├── signature-request/SKILL.md
    ├── triage-nda/SKILL.md
    └── vendor-check/SKILL.md
```

**No `hooks/`. No `agents/`. No `commands/`. No `scripts/`. No `bin/`. No `monitors/`. No bundled `vendor/`.** The MCP servers (Slack, Box, Egnyte, Atlassian, etc.) are declared in `.mcp.json` as HTTP endpoints — they ship *separately* from the plugin.

**Direct user directive (2026-04-21):**
> *"https://github.com/anthropics/knowledge-work-plugins — the mcp has the scripts not the plugin"*

Therefore this plan re-parents every capability the spec pinned in the plugin:

| Spec §5 location | Actual implementation site |
|---|---|
| `hooks/redact.py` (PreToolUse outbound) | Skill prose instructs the model to call `mcp__hacienda__anonymize_text` before any outbound tool. **No seatbelt hook in v1.** |
| `hooks/rehydrate.py` (PostToolUse retrieval) | piighost already returns redacted excerpts; rehydration is a tool call (`mcp__hacienda__rehydrate_text`), not a hook. |
| `commands/*.md` | Each command becomes a skill under `skills/<name>/SKILL.md` with `argument-hint` frontmatter. In the legal reference, skills ARE slash commands. |
| `agents/redaction-agent.md` | Removed from v1. Cowork plugin agent wiring is not present in the reference and is out of scope. |
| `monitors/monitors.json` | Removed from v1. No monitor primitive in the reference. Status is a polled MCP resource. |
| `bin/hacienda-bootstrap` | `bootstrap_client_folder` MCP tool on piighost, invoked by the `knowledge-base` skill on first use. |
| `vendor/piighost/` bundled runtime | `.mcp.json` invokes piighost via `uvx piighost` (or `python -m piighost.mcp`). No vendoring in v1; piighost installs as a normal Python package. |

**Confidentiality trade-off (honest):** Without PreToolUse hooks, v1 cannot *enforce* outbound redaction. It *strongly guides* the model via skill prose + already-redacted retrieval output (piighost's search tools return placeholders by design). Every skill that drafts outbound content explicitly tells the model to call `anonymize_text` on any excerpt before putting it in a Slack/email/webfetch tool call. This is the same trust-based pattern every Cowork plugin uses.

V2 can add a PreToolUse hook mechanism if/when Cowork exposes one. The public spec section on "redacted-transit" stays accurate in intent; the mechanism is now prose + tool composition, not Python hooks.

---

## Cowork Plugin Contract (Reference)

From the `legal/` plugin, verified file-by-file:

**`.claude-plugin/plugin.json`:**
```json
{
  "name": "legal",
  "version": "1.2.0",
  "description": "Speed up contract review, NDA triage, and compliance workflows for in-house legal teams. Draft legal briefs, organize precedent research, and manage institutional knowledge.",
  "author": { "name": "Anthropic" }
}
```
Fields: `name`, `version`, `description`, `author.name`. No `tools`, no `hooks`, no `commands`, no `agents`, no `permissions` — Cowork doesn't read those here.

**`.mcp.json`:**
```json
{
  "mcpServers": {
    "slack":      { "type": "http", "url": "https://mcp.slack.com/mcp" },
    "box":        { "type": "http", "url": "https://mcp.box.com" },
    "egnyte":     { "type": "http", "url": "https://mcp-server.egnyte.com/mcp" },
    "atlassian":  { "type": "http", "url": "https://mcp.atlassian.com/v1/mcp" },
    "ms365":      { "type": "http", "url": "https://microsoft365.mcp.claude.com/mcp" }
  }
}
```
Same schema as the client's `~/.claude.json`. Supports `type: "http"` (URL) and `type: "stdio"` (command + args).

**`skills/<name>/SKILL.md` frontmatter (from `legal/skills/brief/SKILL.md`):**
```yaml
---
name: brief
description: Generate contextual briefings for legal work — daily summary, topic research, or incident response. Use when starting your day and need a scan of legal-relevant items across email, calendar, and contracts, when researching a specific legal question across internal sources, or when a developing situation (data breach, litigation threat, regulatory inquiry) needs rapid context.
argument-hint: "[daily | topic <query> | incident]"
---
```
Keys allowed: `name`, `description`, `argument-hint`. Nothing else. (No `tools`, no `allowed-tools`, no Python.) The skill name becomes the slash command: `/brief daily`. Arguments are referenced as `$1`, `$2`, etc. or as `@$1` (to accept a file path).

**`CONNECTORS.md`** documents the `~~category` placeholder convention (e.g. `~~cloud storage` means any MCP server in the cloud-storage category). Plugins are tool-agnostic; users connect whichever provider they use.

---

## File Structure

**Two repos, two worktrees:**

### Repo 1: `piighost` (existing, this repo)

New/modified files, all inside the existing `src/piighost/` tree:

| File | Purpose |
|---|---|
| `src/piighost/mcp/server.py` | Wire up the new tools and resources (modify) |
| `src/piighost/mcp/folder.py` | **New.** `project_name_for_folder(path)` deterministic hasher |
| `src/piighost/mcp/audit.py` | **New.** Per-session append-only JSONL audit log |
| `src/piighost/mcp/bootstrap.py` | **New.** Idempotent data-dir + vault-key + project setup |
| `tests/unit/test_mcp_folder.py` | **New.** Unit tests for the hasher |
| `tests/unit/test_mcp_audit.py` | **New.** Unit tests for the session audit |
| `tests/unit/test_mcp_bootstrap.py` | **New.** Unit tests for bootstrap |
| `tests/unit/test_mcp_server_hacienda.py` | **New.** Integration tests for the new MCP surface |
| `tests/e2e/test_hacienda_cowork_smoke.py` | **New.** End-to-end smoke: index a sample folder, run skill prose as a script |

### Repo 2: `jamon8888/hacienda` (NEW, separate public repo)

Initialised fresh. Mirrors the `legal/` plugin layout exactly:

```
hacienda/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json
├── CONNECTORS.md
├── LICENSE                 # MIT
├── README.md               # EN + FR sections
└── skills/
    ├── knowledge-base/
    │   └── SKILL.md        # core search skill (passive guidance, no argument-hint)
    ├── ask/
    │   └── SKILL.md        # /ask <question> — invokes knowledge-base
    ├── index/
    │   └── SKILL.md        # /index [full|incremental] — force (re)index
    ├── status/
    │   └── SKILL.md        # /status — show index state
    ├── audit/
    │   └── SKILL.md        # /audit — per-session redaction report
    └── redact-outbound/
        └── SKILL.md        # passive guidance on placeholder semantics
```

Plugin repo is separate from piighost to keep branding clean and to let the marketplace listing link to a dedicated source.

---

## Task Summary

| # | Task | Site |
|---|---|---|
| 1 | Worktree + branch setup (both repos) | both |
| 2 | `project_name_for_folder` helper + tests | piighost |
| 3 | `resolve_project_for_folder` MCP tool + tests | piighost |
| 4 | Upgrade `piighost://index/status` to structured JSON | piighost |
| 5 | Parameterised `piighost://folders/{path}/status` resource | piighost |
| 6 | Session audit log + `session_audit_append` / `session_audit_read` tools | piighost |
| 7 | `bootstrap_client_folder` MCP tool + tests | piighost |
| 8 | Hacienda repo scaffold — `.claude-plugin/plugin.json`, `LICENSE`, `.gitignore` | hacienda |
| 9 | `.mcp.json` wiring piighost as stdio server | hacienda |
| 10 | `skills/knowledge-base/SKILL.md` | hacienda |
| 11 | `skills/ask/SKILL.md` (`/ask <question>`) | hacienda |
| 12 | `skills/index/SKILL.md` (`/index [path]`) | hacienda |
| 13 | `skills/status/SKILL.md` (`/status`) | hacienda |
| 14 | `skills/audit/SKILL.md` (`/audit`) | hacienda |
| 15 | `skills/redact-outbound/SKILL.md` | hacienda |
| 16 | `CONNECTORS.md` | hacienda |
| 17 | `README.md` (EN + FR) | hacienda |
| 18 | E2E smoke test + CI gate | piighost |
| 19 | Marketplace metadata + release tag | hacienda |

---

## Task 1: Worktree + branch setup

**Files:**
- Worktree for piighost: `C:\Users\NMarchitecte\Documents\piighost\.worktrees\hacienda-mcp`
- Worktree for hacienda: `C:\Users\NMarchitecte\Documents\piighost\.worktrees\hacienda-plugin` (no upstream yet — this worktree initialises a fresh repo)

- [ ] **Step 1: Create piighost worktree**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git worktree add .worktrees/hacienda-mcp -b feat/hacienda-mcp-surface
```

Expected: `Preparing worktree (new branch 'feat/hacienda-mcp-surface')`

- [ ] **Step 2: Verify .worktrees is gitignored**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git check-ignore -q .worktrees && echo IGNORED || echo NOT_IGNORED
```

Expected: `IGNORED`. If `NOT_IGNORED`, append `.worktrees/` to `.gitignore`, commit, re-run.

- [ ] **Step 3: Create hacienda plugin workspace (fresh init)**

```bash
cd /c/Users/NMarchitecte/Documents/piighost/.worktrees
mkdir hacienda-plugin && cd hacienda-plugin
git init -b main
```

Expected: `Initialized empty Git repository`. This workspace is *not* a worktree of piighost — hacienda is a separate repo. It lives under piighost's `.worktrees/` for convenience during development only.

- [ ] **Step 4: Install piighost dev dependencies in the MCP worktree**

```bash
cd /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-mcp
uv sync --dev --extra index --extra mcp
```

Expected: `Installed N packages`.

- [ ] **Step 5: Run baseline tests**

```bash
cd /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-mcp
uv run pytest tests/unit/test_mcp_server.py -q
```

Expected: PASS for whatever MCP tests currently exist. Record pass count for later comparison.

---

## Task 2: `project_name_for_folder` helper

**Goal:** Pure function that maps an absolute folder path to a deterministic project name (`<slugified-leaf>-<hash8>`). No I/O. Same input always produces the same output. Cross-platform path normalisation (Windows drive letters folded to lowercase, separators normalised, trailing slashes stripped).

**Files:**
- Create: `src/piighost/mcp/folder.py`
- Create: `tests/unit/test_mcp_folder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_folder.py
"""Deterministic folder → project-name hasher for hacienda."""
from __future__ import annotations

from pathlib import Path

from piighost.mcp.folder import project_name_for_folder


class TestProjectNameForFolder:
    def test_stable_for_same_path(self) -> None:
        a = project_name_for_folder(Path("/home/user/Dossiers/ACME"))
        b = project_name_for_folder(Path("/home/user/Dossiers/ACME"))
        assert a == b

    def test_different_paths_different_names(self) -> None:
        a = project_name_for_folder(Path("/home/user/Dossiers/ACME"))
        b = project_name_for_folder(Path("/home/user/Dossiers/BETA"))
        assert a != b

    def test_windows_case_insensitive(self) -> None:
        # Windows paths: drive letter case must not matter.
        a = project_name_for_folder(Path(r"C:\Users\Maitre\Dossiers\ACME"))
        b = project_name_for_folder(Path(r"c:\Users\Maitre\Dossiers\ACME"))
        assert a == b

    def test_trailing_separator_ignored(self) -> None:
        a = project_name_for_folder(Path("/home/user/ACME"))
        b = project_name_for_folder(Path("/home/user/ACME/"))
        assert a == b

    def test_format_is_slug_dash_hash8(self) -> None:
        name = project_name_for_folder(Path("/home/user/Dossiers/ACME Inc."))
        # "acme-inc-" slug + 8 hex chars hash
        assert "-" in name
        slug, _, hash_part = name.rpartition("-")
        assert len(hash_part) == 8
        assert all(c in "0123456789abcdef" for c in hash_part)
        assert slug == "acme-inc"

    def test_empty_leaf_falls_back_to_root(self) -> None:
        # Path("/") has empty .name — hasher must still produce a valid name.
        name = project_name_for_folder(Path("/"))
        assert name  # non-empty
        assert name.endswith(tuple("0123456789abcdef"))
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-mcp
uv run pytest tests/unit/test_mcp_folder.py -v
```

Expected: `ModuleNotFoundError: No module named 'piighost.mcp.folder'`.

- [ ] **Step 3: Implement the helper**

```python
# src/piighost/mcp/folder.py
"""Deterministic mapping from an absolute folder path to a piighost project name.

Cowork hands us the user's current folder as an absolute path. We need a project
identifier that (a) is stable across runs, (b) differs for distinct folders, (c)
normalises Windows case/separators so the same folder from two different
shells maps to the same project.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(leaf: str) -> str:
    """Lowercase, collapse non-alnum to single '-', strip edges."""
    slug = _SLUG_RE.sub("-", leaf.lower()).strip("-")
    return slug or "root"


def _normalise(path: Path) -> str:
    """Canonical string form used for hashing. Case-insensitive, no trailing sep."""
    # Resolve-free: we only want textual normalisation — the folder may not
    # exist yet at tool-call time (Cowork may open a brand-new folder).
    raw = str(path)
    # Windows: fold case and normalise separators.
    raw = raw.replace("\\", "/").rstrip("/").lower()
    return raw


def project_name_for_folder(path: Path) -> str:
    """Map an absolute folder path to a piighost project name.

    Format: ``<slug>-<hash8>`` where ``slug`` is a kebab-case version of the
    folder's leaf name (``ACME Inc.`` → ``acme-inc``) and ``hash8`` is the first
    8 hex chars of SHA-256 over the normalised full path. The slug keeps names
    human-readable in ``list_projects`` output; the hash guarantees uniqueness
    even when two clients share a leaf name.
    """
    leaf = path.name or path.anchor or "root"
    slug = _slugify(leaf)
    digest = hashlib.sha256(_normalise(path).encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"
```

- [ ] **Step 4: Run tests — verify all pass**

```bash
uv run pytest tests/unit/test_mcp_folder.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/folder.py tests/unit/test_mcp_folder.py
git commit -m "feat(mcp): deterministic folder → project-name hasher for hacienda"
```

---

## Task 3: `resolve_project_for_folder` MCP tool

**Goal:** Expose `project_name_for_folder` as an MCP tool so the hacienda skills can resolve the active Cowork folder without duplicating the hash logic in prose.

**Files:**
- Modify: `src/piighost/mcp/server.py` — register a new tool
- Create: `tests/unit/test_mcp_server_hacienda.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_server_hacienda.py
"""MCP surface additions that back the hacienda Cowork plugin."""
from __future__ import annotations

from pathlib import Path

import pytest

from piighost.mcp.server import build_mcp


@pytest.mark.asyncio
class TestResolveProjectForFolder:
    async def test_returns_project_name_and_folder(self, tmp_path: Path) -> None:
        mcp, svc = await build_mcp(vault_dir=tmp_path / "vault")
        try:
            tool = await mcp.get_tool("resolve_project_for_folder")
            result = await tool.run({"folder": "/home/user/Dossiers/ACME"})
            # FastMCP wraps the return in a Pydantic model; unwrap to dict.
            data = result.structured_content
            assert data["folder"] == "/home/user/Dossiers/ACME"
            assert data["project"].startswith("acme-")
            assert len(data["project"].rsplit("-", 1)[1]) == 8
        finally:
            await svc.close()

    async def test_same_folder_same_project(self, tmp_path: Path) -> None:
        mcp, svc = await build_mcp(vault_dir=tmp_path / "vault")
        try:
            tool = await mcp.get_tool("resolve_project_for_folder")
            a = await tool.run({"folder": "/home/user/ACME"})
            b = await tool.run({"folder": "/home/user/ACME"})
            assert a.structured_content["project"] == b.structured_content["project"]
        finally:
            await svc.close()
```

- [ ] **Step 2: Run the test — verify it fails**

```bash
uv run pytest tests/unit/test_mcp_server_hacienda.py::TestResolveProjectForFolder -v
```

Expected: `AttributeError` or `KeyError` — no such tool.

- [ ] **Step 3: Register the tool in `build_mcp`**

Find the end of the tool registrations in `src/piighost/mcp/server.py` (after `daemon_stop`, before the `@mcp.resource` decorators, around line 145), and insert:

```python
    from piighost.mcp.folder import project_name_for_folder

    @mcp.tool(
        description=(
            "Resolve the Cowork active folder to its piighost project name. "
            "Deterministic: same folder always maps to the same project. "
            "Use this in every hacienda skill before calling index_path or query."
        )
    )
    async def resolve_project_for_folder(folder: str) -> dict:
        project = project_name_for_folder(Path(folder))
        return {"folder": folder, "project": project}
```

- [ ] **Step 4: Run the tests — verify pass**

```bash
uv run pytest tests/unit/test_mcp_server_hacienda.py::TestResolveProjectForFolder -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/server.py tests/unit/test_mcp_server_hacienda.py
git commit -m "feat(mcp): add resolve_project_for_folder tool for hacienda skills"
```

---

## Task 4: Upgrade `piighost://index/status` to structured JSON

**Goal:** Cowork plugins surface status as MCP resources. The current resource returns human-readable plain text (`f"Indexed documents: {len(doc_ids)}\n..."`). For hacienda's status skill to be useful, we need JSON with `state`, `total_docs`, `total_chunks`, `last_update`, `errors`.

**Files:**
- Modify: `src/piighost/mcp/server.py`
- Modify: `tests/unit/test_mcp_server_hacienda.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_mcp_server_hacienda.py`:

```python
@pytest.mark.asyncio
class TestIndexStatusResource:
    async def test_returns_json_with_expected_keys(self, tmp_path: Path) -> None:
        import json
        mcp, svc = await build_mcp(vault_dir=tmp_path / "vault")
        try:
            resources = await mcp.get_resources()
            status = resources["piighost://index/status"]
            payload = await status.read()
            data = json.loads(payload)
            assert set(data.keys()) >= {
                "state", "total_docs", "total_chunks", "last_update", "errors"
            }
            assert data["state"] in {"ready", "indexing", "error", "empty"}
            assert isinstance(data["total_docs"], int)
            assert isinstance(data["errors"], list)
        finally:
            await svc.close()
```

- [ ] **Step 2: Run test — verify fail**

```bash
uv run pytest tests/unit/test_mcp_server_hacienda.py::TestIndexStatusResource -v
```

Expected: `json.JSONDecodeError` (resource currently returns `"Indexed documents: 0\nTotal chunks: 0"`).

- [ ] **Step 3: Replace the resource implementation**

In `src/piighost/mcp/server.py`, find the existing `@mcp.resource("piighost://index/status")` block (around line 157) and replace its body:

```python
    @mcp.resource("piighost://index/status")
    async def index_status_resource() -> str:
        import json
        records = svc._chunk_store.all_records()
        doc_ids = {r["doc_id"] for r in records}
        if not doc_ids:
            state = "empty"
        else:
            state = "ready"
        last_update = max(
            (r.get("indexed_at", "") for r in records), default=""
        )
        payload = {
            "state": state,
            "total_docs": len(doc_ids),
            "total_chunks": len(records),
            "last_update": last_update,
            "errors": [],
        }
        return json.dumps(payload)
```

> If `indexed_at` is not currently stored on chunk records, fall back to `""`. We don't want to fail this task on a missing field; the e2e test in Task 18 will flag it if it matters for users.

- [ ] **Step 4: Run tests — verify pass**

```bash
uv run pytest tests/unit/test_mcp_server_hacienda.py::TestIndexStatusResource -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/server.py tests/unit/test_mcp_server_hacienda.py
git commit -m "feat(mcp): return structured JSON from piighost://index/status"
```

---

## Task 5: Parameterised `piighost://folders/{path}/status` resource

**Goal:** Per-folder status. Lets Cowork show a status chip specifically for the currently-opened folder (`Hacienda · ACME · indexing 32%`).

**Note on URI encoding:** the folder path can contain slashes and Windows drive letters. We base64url-encode it in the URI: `piighost://folders/{b64_path}/status` where `b64_path = base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")`.

**Files:**
- Modify: `src/piighost/mcp/server.py`
- Modify: `tests/unit/test_mcp_server_hacienda.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_mcp_server_hacienda.py`:

```python
@pytest.mark.asyncio
class TestFolderStatusResource:
    async def test_per_folder_status_uses_project_hash(self, tmp_path: Path) -> None:
        import base64
        import json
        mcp, svc = await build_mcp(vault_dir=tmp_path / "vault")
        try:
            folder = str(tmp_path / "clients" / "ACME")
            b64 = base64.urlsafe_b64encode(folder.encode()).decode().rstrip("=")
            resources = await mcp.get_resources()
            # Parameterised resources register by template, not by URI.
            template = resources[f"piighost://folders/{{b64_path}}/status"]
            payload = await template.read({"b64_path": b64})
            data = json.loads(payload)
            assert data["folder"] == folder
            assert data["project"].startswith("acme-")
            assert data["state"] in {"ready", "indexing", "error", "empty"}
        finally:
            await svc.close()
```

> If `get_resources()` returns templates under a different key, adjust to match FastMCP's actual API. Fallback: read the resource by URI using `mcp._resource_manager.get_resource(uri)`.

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest tests/unit/test_mcp_server_hacienda.py::TestFolderStatusResource -v
```

Expected: `KeyError` — no such resource template.

- [ ] **Step 3: Add the resource**

Append to `src/piighost/mcp/server.py`, after the `index_status_resource` function:

```python
    @mcp.resource("piighost://folders/{b64_path}/status")
    async def folder_status_resource(b64_path: str) -> str:
        import base64
        import json
        # Decode folder path. Pad if stripped.
        padding = "=" * (-len(b64_path) % 4)
        try:
            folder = base64.urlsafe_b64decode(b64_path + padding).decode("utf-8")
        except Exception:
            return json.dumps({"error": "invalid base64url folder path"})
        project = project_name_for_folder(Path(folder))
        try:
            status = await svc.index_status(project=project)
        except Exception as exc:  # project may not exist yet
            return json.dumps({
                "folder": folder,
                "project": project,
                "state": "empty",
                "progress": {"done": 0, "total": 0},
                "last_update": "",
                "errors": [str(exc)],
            })
        payload = {
            "folder": folder,
            "project": project,
            "state": "ready" if status.total_docs else "empty",
            "progress": {"done": status.total_docs, "total": status.total_docs},
            "last_update": getattr(status, "last_update", "") or "",
            "errors": [],
        }
        return json.dumps(payload)
```

- [ ] **Step 4: Run tests — verify pass**

```bash
uv run pytest tests/unit/test_mcp_server_hacienda.py::TestFolderStatusResource -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/server.py tests/unit/test_mcp_server_hacienda.py
git commit -m "feat(mcp): per-folder status resource piighost://folders/{path}/status"
```

---

## Task 6: Session audit log

**Goal:** Append-only JSONL per session, stored under `~/.hacienda/sessions/<session_id>.audit.jsonl`. Records every anonymize/rehydrate call so `/audit` can reconstruct what went to the cloud and what came back.

**Files:**
- Create: `src/piighost/mcp/audit.py`
- Create: `tests/unit/test_mcp_audit.py`
- Modify: `src/piighost/mcp/server.py` — register `session_audit_append` and `session_audit_read` tools

- [ ] **Step 1: Write failing tests for the audit module**

```python
# tests/unit/test_mcp_audit.py
"""Per-session append-only audit log."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from piighost.mcp.audit import SessionAudit


class TestSessionAudit:
    def test_append_writes_jsonl(self, tmp_path: Path) -> None:
        audit = SessionAudit(root=tmp_path, session_id="sess-1")
        audit.append("anonymize", {"doc": "a.pdf", "n_entities": 3})
        audit.append("rehydrate", {"tokens": ["PER_001"]})
        file = tmp_path / "sessions" / "sess-1.audit.jsonl"
        assert file.exists()
        lines = file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["event"] == "anonymize"
        assert first["payload"] == {"doc": "a.pdf", "n_entities": 3}
        assert "timestamp" in first

    def test_read_returns_parsed_events(self, tmp_path: Path) -> None:
        audit = SessionAudit(root=tmp_path, session_id="sess-2")
        audit.append("anonymize", {"n": 1})
        audit.append("anonymize", {"n": 2})
        events = audit.read()
        assert [e["payload"]["n"] for e in events] == [1, 2]

    def test_read_empty_session_returns_empty_list(self, tmp_path: Path) -> None:
        audit = SessionAudit(root=tmp_path, session_id="never-used")
        assert audit.read() == []

    def test_append_refuses_nonserialisable(self, tmp_path: Path) -> None:
        audit = SessionAudit(root=tmp_path, session_id="sess-3")
        with pytest.raises(TypeError):
            audit.append("event", {"bad": object()})

    def test_session_id_validated(self, tmp_path: Path) -> None:
        # No path traversal via session id.
        with pytest.raises(ValueError):
            SessionAudit(root=tmp_path, session_id="../etc/passwd")

    def test_append_never_logs_raw_pii_values(self, tmp_path: Path) -> None:
        """Safety invariant: the audit payload must not contain raw PII.

        Callers pass placeholders + vault tokens only. This test documents
        the contract — the audit module doesn't enforce it (can't), but any
        future contributor grepping for 'test_append_never_logs_raw_pii' will
        be reminded.
        """
        audit = SessionAudit(root=tmp_path, session_id="sess-4")
        audit.append("anonymize", {"placeholder": "«PER_001»", "token": "tok_abc"})
        events = audit.read()
        assert events[0]["payload"]["placeholder"] == "«PER_001»"
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest tests/unit/test_mcp_audit.py -v
```

Expected: `ModuleNotFoundError: No module named 'piighost.mcp.audit'`.

- [ ] **Step 3: Implement `SessionAudit`**

```python
# src/piighost/mcp/audit.py
"""Per-session append-only audit log for hacienda redaction events.

Records each anonymize/rehydrate call plus metadata (timestamp, event name,
payload). Payloads MUST NOT contain raw PII — callers pass placeholders and
vault tokens only. This is a safety-critical invariant; we document it in
tests but cannot enforce it structurally without taking a dependency on the
vault encryption layer.

Storage: ``<root>/sessions/<session_id>.audit.jsonl``. JSONL so partial
writes never corrupt prior events.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class SessionAudit:
    def __init__(self, *, root: Path, session_id: str) -> None:
        if not _SESSION_ID_RE.match(session_id):
            raise ValueError(f"invalid session id: {session_id!r}")
        self._file = root / "sessions" / f"{session_id}.audit.jsonl"
        self._file.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, payload: dict[str, Any]) -> None:
        """Append a single event line. Raises TypeError on non-serialisable payloads."""
        record = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "event": event,
            "payload": payload,
        }
        # json.dumps raises TypeError for non-serialisable values — we let it propagate.
        line = json.dumps(record, ensure_ascii=False)
        with self._file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self._file.exists():
            return []
        out: list[dict[str, Any]] = []
        with self._file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out
```

- [ ] **Step 4: Run unit tests — verify pass**

```bash
uv run pytest tests/unit/test_mcp_audit.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Register audit MCP tools**

In `src/piighost/mcp/server.py`, at the top add:

```python
import os
```

After the `resolve_project_for_folder` tool registration (from Task 3), add:

```python
    from piighost.mcp.audit import SessionAudit

    def _audit_for(session_id: str) -> SessionAudit:
        root = Path(os.environ.get("HACIENDA_DATA_DIR", Path.home() / ".hacienda"))
        return SessionAudit(root=root, session_id=session_id)

    @mcp.tool(
        description=(
            "Append an event to the current Cowork session's audit log. "
            "Payload MUST use placeholders/tokens only, never raw PII. "
            "Called by hacienda skills after each anonymize/rehydrate round-trip."
        )
    )
    async def session_audit_append(
        session_id: str, event: str, payload: dict
    ) -> dict:
        _audit_for(session_id).append(event, payload)
        return {"ok": True}

    @mcp.tool(
        description=(
            "Read the current Cowork session's redaction audit log. "
            "Returns a list of {timestamp, event, payload} records in write order."
        )
    )
    async def session_audit_read(session_id: str) -> list[dict]:
        return _audit_for(session_id).read()
```

- [ ] **Step 6: Write integration test for the tools**

Append to `tests/unit/test_mcp_server_hacienda.py`:

```python
@pytest.mark.asyncio
class TestSessionAuditTools:
    async def test_append_then_read(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HACIENDA_DATA_DIR", str(tmp_path))
        mcp, svc = await build_mcp(vault_dir=tmp_path / "vault")
        try:
            append = await mcp.get_tool("session_audit_append")
            read = await mcp.get_tool("session_audit_read")
            await append.run({
                "session_id": "s1",
                "event": "anonymize",
                "payload": {"n": 3},
            })
            await append.run({
                "session_id": "s1",
                "event": "rehydrate",
                "payload": {"n": 3},
            })
            result = await read.run({"session_id": "s1"})
            events = result.structured_content
            # FastMCP may wrap list returns under a "result" key — handle both.
            if isinstance(events, dict) and "result" in events:
                events = events["result"]
            assert len(events) == 2
            assert events[0]["event"] == "anonymize"
            assert events[1]["event"] == "rehydrate"
        finally:
            await svc.close()
```

- [ ] **Step 7: Run full hacienda test module — verify pass**

```bash
uv run pytest tests/unit/test_mcp_server_hacienda.py tests/unit/test_mcp_audit.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/piighost/mcp/audit.py src/piighost/mcp/server.py tests/unit/test_mcp_audit.py tests/unit/test_mcp_server_hacienda.py
git commit -m "feat(mcp): per-session redaction audit log + append/read tools"
```

---

## Task 7: `bootstrap_client_folder` MCP tool

**Goal:** Idempotent one-shot that a hacienda skill calls on first use of a folder. Ensures: data dir exists, vault key is set, project is created.

**Files:**
- Create: `src/piighost/mcp/bootstrap.py`
- Create: `tests/unit/test_mcp_bootstrap.py`
- Modify: `src/piighost/mcp/server.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_mcp_bootstrap.py
"""Idempotent bootstrap for a Cowork client folder."""
from __future__ import annotations

from pathlib import Path

import pytest

from piighost.mcp.bootstrap import ensure_data_dir, ensure_vault_key


class TestEnsureDataDir:
    def test_creates_when_missing(self, tmp_path: Path) -> None:
        target = tmp_path / ".hacienda"
        assert not target.exists()
        ensure_data_dir(target)
        assert target.is_dir()
        assert (target / "sessions").is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / ".hacienda"
        ensure_data_dir(target)
        ensure_data_dir(target)  # must not raise
        assert target.is_dir()


class TestEnsureVaultKey:
    def test_returns_existing_key(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("CLOAKPIPE_VAULT_KEY", "abc123" * 10)
        key = ensure_vault_key(data_dir=tmp_path)
        assert key == "abc123" * 10

    def test_generates_and_persists_when_missing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.delenv("CLOAKPIPE_VAULT_KEY", raising=False)
        key = ensure_vault_key(data_dir=tmp_path)
        assert len(key) >= 32
        # Second call returns the same key.
        assert ensure_vault_key(data_dir=tmp_path) == key
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest tests/unit/test_mcp_bootstrap.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the bootstrap helpers**

```python
# src/piighost/mcp/bootstrap.py
"""First-run helpers for hacienda folders.

Idempotent by design — every hacienda skill calls ``bootstrap_client_folder``
on every invocation. Re-running must be cheap and must never rotate the
vault key (doing so would orphan every placeholder in the existing index).
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path


def ensure_data_dir(root: Path) -> None:
    """Create ``<root>/`` and ``<root>/sessions/`` if missing. Idempotent."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "sessions").mkdir(parents=True, exist_ok=True)


_KEY_FILE = "vault.key"


def ensure_vault_key(*, data_dir: Path) -> str:
    """Return the vault key, generating and persisting if absent.

    Priority: ``CLOAKPIPE_VAULT_KEY`` env var → ``<data_dir>/vault.key`` file
    → new random key written to the file. The file is chmod 0600 on Unix.

    **Never** rotates: existing keys are returned untouched. Rotating would
    orphan the encrypted vault entries and break rehydration of prior
    placeholders.
    """
    env_key = os.environ.get("CLOAKPIPE_VAULT_KEY")
    if env_key:
        return env_key

    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / _KEY_FILE
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()

    new_key = secrets.token_urlsafe(48)  # 64-char url-safe
    key_path.write_text(new_key, encoding="utf-8")
    try:
        os.chmod(key_path, 0o600)
    except OSError:  # Windows — ignore permission errors
        pass
    return new_key
```

- [ ] **Step 4: Run — verify pass**

```bash
uv run pytest tests/unit/test_mcp_bootstrap.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Register the MCP tool**

In `src/piighost/mcp/server.py`, after the audit tools:

```python
    from piighost.mcp.bootstrap import ensure_data_dir, ensure_vault_key

    @mcp.tool(
        description=(
            "Idempotent first-run setup for a Cowork client folder. "
            "Ensures the hacienda data directory and vault key exist, creates "
            "the project if missing. Safe to call on every session start."
        )
    )
    async def bootstrap_client_folder(folder: str) -> dict:
        from piighost.mcp.folder import project_name_for_folder
        data_dir = Path(
            os.environ.get("HACIENDA_DATA_DIR", Path.home() / ".hacienda")
        )
        ensure_data_dir(data_dir)
        key = ensure_vault_key(data_dir=data_dir)
        project = project_name_for_folder(Path(folder))

        existing = {p.name for p in await svc.list_projects()}
        if project not in existing:
            await svc.create_project(project, description=f"Cowork folder: {folder}")

        return {
            "folder": folder,
            "project": project,
            "data_dir": str(data_dir),
            "vault_key_provisioned": bool(key),
        }
```

- [ ] **Step 6: Add integration test**

Append to `tests/unit/test_mcp_server_hacienda.py`:

```python
@pytest.mark.asyncio
class TestBootstrapClientFolder:
    async def test_creates_project_and_data_dir(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("HACIENDA_DATA_DIR", str(tmp_path / "hdata"))
        monkeypatch.setenv("CLOAKPIPE_VAULT_KEY", "x" * 48)
        mcp, svc = await build_mcp(vault_dir=tmp_path / "vault")
        try:
            tool = await mcp.get_tool("bootstrap_client_folder")
            result = await tool.run({"folder": str(tmp_path / "ACME")})
            data = result.structured_content
            assert data["project"].startswith("acme-")
            assert (tmp_path / "hdata").is_dir()
            projects = {p.name for p in await svc.list_projects()}
            assert data["project"] in projects
        finally:
            await svc.close()

    async def test_idempotent(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HACIENDA_DATA_DIR", str(tmp_path / "hdata"))
        monkeypatch.setenv("CLOAKPIPE_VAULT_KEY", "x" * 48)
        mcp, svc = await build_mcp(vault_dir=tmp_path / "vault")
        try:
            tool = await mcp.get_tool("bootstrap_client_folder")
            a = await tool.run({"folder": str(tmp_path / "ACME")})
            b = await tool.run({"folder": str(tmp_path / "ACME")})
            assert a.structured_content["project"] == b.structured_content["project"]
        finally:
            await svc.close()
```

- [ ] **Step 7: Run — verify pass**

```bash
uv run pytest tests/unit/test_mcp_bootstrap.py tests/unit/test_mcp_server_hacienda.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/piighost/mcp/bootstrap.py src/piighost/mcp/server.py tests/unit/test_mcp_bootstrap.py tests/unit/test_mcp_server_hacienda.py
git commit -m "feat(mcp): bootstrap_client_folder tool for hacienda first-run"
```

---

## Task 8: Hacienda repo scaffold

**Files** (all created fresh in `C:\Users\NMarchitecte\Documents\piighost\.worktrees\hacienda-plugin\`):
- `.claude-plugin/plugin.json`
- `LICENSE`
- `.gitignore`

- [ ] **Step 1: Create `.claude-plugin/plugin.json`**

```bash
mkdir -p .claude-plugin
```

Write `.claude-plugin/plugin.json`:

```json
{
  "name": "hacienda",
  "version": "0.1.0",
  "description": "PII-safe RAG over your client folders, directly inside Claude Desktop. Built for regulated professionals (avocats, notaires, experts-comptables, médecins) bound by professional secrecy. Indexes folders locally, redacts outbound requests, cites sources.",
  "author": {
    "name": "piighost team"
  }
}
```

- [ ] **Step 2: Write `LICENSE` (MIT)**

```
MIT License

Copyright (c) 2026 piighost team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 3: Write `.gitignore`**

```
.DS_Store
*.log
*.tmp
node_modules/
.venv/
__pycache__/
```

- [ ] **Step 4: Initial commit**

```bash
cd /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-plugin
git add .claude-plugin/plugin.json LICENSE .gitignore
git commit -m "chore: initial plugin scaffold (plugin.json, LICENSE)"
```

---

## Task 9: `.mcp.json` wiring piighost as a stdio server

**Goal:** Declare the piighost MCP server as a stdio child process. Users install piighost via `pip` or `uvx` once; the plugin launches it on demand.

**Files:**
- Create: `.mcp.json` in the hacienda plugin root

- [ ] **Step 1: Write `.mcp.json`**

```json
{
  "mcpServers": {
    "hacienda": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "piighost", "piighost", "serve", "--transport", "stdio"],
      "env": {
        "HACIENDA_DATA_DIR": "${HOME}/.hacienda"
      }
    }
  }
}
```

> **Naming note:** the server is *aliased* as `hacienda` inside this plugin. Cowork exposes its tools as `mcp__hacienda__<tool_name>`. This lets skill prose reference `mcp__hacienda__query` even though the upstream server calls itself `piighost`.

> **Command note:** `uvx` is Astral's uv execute-tool wrapper. If a user lacks uv, the README fallback command is `pip install piighost && python -m piighost serve --transport stdio`. We default to `uvx` because it handles the extras automatically.

> **Verification gap (open question):** does `piighost serve` accept `--transport stdio`? Confirm against the CLI when Task 18 runs the e2e smoke test. If the flag differs, update `.mcp.json`.

- [ ] **Step 2: Commit**

```bash
git add .mcp.json
git commit -m "feat: wire piighost MCP server via stdio as 'hacienda'"
```

---

## Task 10: `skills/knowledge-base/SKILL.md`

**Goal:** The core skill. Not a slash command (no `argument-hint`) — the model invokes it whenever the user asks a question about the current folder. All three other user-facing slash commands (`/ask`, `/index`, `/status`) reference this skill.

**Files:**
- Create: `skills/knowledge-base/SKILL.md`

- [ ] **Step 1: Write the skill**

````markdown
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
hacienda://folders/{b64_path}/status
```

where `b64_path = base64.urlsafe_b64encode(folder.encode()).decode().rstrip("=")`.

- `state == "empty"` or `state == "indexing"`: tell the user *"Indexing this folder — I'll answer as soon as it's ready. You can also run `/index` to force a full scan."* and call `mcp__hacienda__index_path(path=<folder>, project=<project>)` in the background.
- `state == "ready"`: proceed.
- `state == "error"`: surface the error list to the user; suggest `/index`.

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
  session_id=<cowork_session_id>,
  event="query",
  payload={"question_hash": <sha256_of_question>, "n_excerpts": <n>, "project": <project>},
)
```

The `question_hash` keeps the audit log meaningful without storing the raw question text.

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
````

- [ ] **Step 2: Commit**

```bash
git add skills/knowledge-base/SKILL.md
git commit -m "feat(skills): knowledge-base — core PII-safe retrieval skill"
```

---

## Task 11: `skills/ask/SKILL.md`

**Goal:** `/ask <question>` slash command. Thin wrapper over `knowledge-base`.

- [ ] **Step 1: Write the skill**

````markdown
---
name: ask
description: Ask a question about the current Cowork folder. Runs PII-safe hybrid retrieval and returns a cited answer. Equivalent to typing the question in chat, but gives the user an explicit slash-command affordance.
argument-hint: "<question>"
---

# /ask — Question the current folder

```
/ask What are the outstanding deliverables under the 2024 SaaS contract?
```

## Workflow

1. Take `$1` as the user's question. If empty, prompt: *"What would you like to ask about this folder?"*
2. Invoke the `knowledge-base` skill workflow with the question.
3. Return the cited answer.

That's it — this skill exists so the user has a discoverable entry point in the slash-command palette. The real work is in `knowledge-base`.

## Example

```
/ask Who signed the NDA dated 2025-03-12?
```

→ knowledge-base resolves the folder, queries piighost, returns an answer citing `nda-2025-03-12.pdf p.3`.
````

- [ ] **Step 2: Commit**

```bash
git add skills/ask/SKILL.md
git commit -m "feat(skills): /ask slash command over knowledge-base"
```

---

## Task 12: `skills/index/SKILL.md`

- [ ] **Step 1: Write the skill**

````markdown
---
name: index
description: Force (re)index the folder currently open in Cowork. Use when files have changed on a network share and the status chip shows stale data, when a new folder was just opened, or when the user explicitly wants a full rescan. Indexing is async — this command starts the job and streams progress from the status resource.
argument-hint: "[full | incremental]"
---

# /index — (Re)index the current folder

```
/index              # incremental (default)
/index full         # rescan everything, re-embed every document
/index incremental  # only changed files (default)
```

## Workflow

1. Parse `$1`: `"full"` → `force=true`, anything else → `force=false`.
2. Call `mcp__hacienda__resolve_project_for_folder(folder=<active>)` → `project`.
3. Call `mcp__hacienda__bootstrap_client_folder(folder=<active>)` (idempotent).
4. Call `mcp__hacienda__index_path(path=<active>, recursive=true, force=<from step 1>, project=<project>)`.
5. Poll `hacienda://folders/{b64_path}/status` every few seconds. Stream progress to the user: *"Indexing: 134 / 247 files …"*.
6. When `state == "ready"`, report: *"Indexed 247 files, 1 823 chunks, 0 errors. Ready."*
7. If `errors` is non-empty, show the list and suggest re-running `/index full` on the affected files.

## Errors

- If the folder does not exist, tell the user and stop.
- If indexing fails mid-way, surface the error from the status resource; do not retry automatically — the user may need to fix a corrupt file first.
````

- [ ] **Step 2: Commit**

```bash
git add skills/index/SKILL.md
git commit -m "feat(skills): /index slash command"
```

---

## Task 13: `skills/status/SKILL.md`

- [ ] **Step 1: Write the skill**

````markdown
---
name: status
description: Show the index state of the folder currently open in Cowork — how many files are indexed, when the last update happened, any errors encountered. Use when the user wants a health check before asking questions, or when troubleshooting unexpected retrieval results.
---

# /status — Folder health

```
/status
```

## Workflow

1. Call `mcp__hacienda__resolve_project_for_folder(folder=<active>)` → `folder, project`.
2. Read `hacienda://folders/{b64_path}/status`.
3. Render:

```
Folder:       <absolute path>
Project:      <project hash>
State:        <ready|indexing|error|empty>
Indexed docs: <total_docs>
Chunks:       <total_chunks>
Last update:  <last_update> (or "never")
Errors:       <n> (list up to 5, then "...and <n-5> more")
```

4. If `state == "empty"`, suggest `/index` to the user.
5. If `last_update` is older than 10 minutes on a network drive, suggest `/index incremental`.
````

- [ ] **Step 2: Commit**

```bash
git add skills/status/SKILL.md
git commit -m "feat(skills): /status slash command"
```

---

## Task 14: `skills/audit/SKILL.md`

- [ ] **Step 1: Write the skill**

````markdown
---
name: audit
description: Show the per-session redaction audit log — which placeholders were generated, which outbound tools were called, what went to the cloud and what came back. Use when the user wants to verify nothing sensitive leaked in this session, or to prepare evidence for a compliance review.
---

# /audit — Per-session redaction report

```
/audit
```

## Workflow

1. Call `mcp__hacienda__session_audit_read(session_id=<cowork_session_id>)`.
2. Summarise:

```
Session <id>

Queries:     <n>
Anonymize:   <n>   (<total_entities> entities redacted)
Rehydrate:   <n>   (<total_tokens> tokens restored)
Outbound:    <n>   (tool × count)

Redaction summary (label × count):
  PER  <n>
  ORG  <n>
  IBAN <n>
  ...

Last event: <timestamp> — <event>
```

3. Offer: *"Show the full event list?"* — if yes, dump the JSONL events one per line, pretty-printed.

## Safety

This report MUST NOT contain raw PII. The audit log stores placeholders, vault tokens, and counts only. If you see any raw value in a payload field, that is a bug — report it as *"Audit corruption detected, contact the plugin author"* and refuse to continue.

## Compliance note

This log is append-only and lives at `~/.hacienda/sessions/<session_id>.audit.jsonl` on the user's device. It is never transmitted off-device by the plugin. Retention: the user may delete files in `~/.hacienda/sessions/` at any time. No cloud copy exists.
````

- [ ] **Step 2: Commit**

```bash
git add skills/audit/SKILL.md
git commit -m "feat(skills): /audit per-session redaction report"
```

---

## Task 15: `skills/redact-outbound/SKILL.md`

**Goal:** Passive guidance skill — no `argument-hint`, just reference for the model when it handles placeholders. Invoked implicitly when a draft is being prepared for an outbound tool.

- [ ] **Step 1: Write the skill**

````markdown
---
name: redact-outbound
description: Rules for handling PII placeholders (like «PER_001», «ORG_014», «IBAN_003») when drafting outbound content — emails, Slack messages, document writes, webfetch payloads. Use whenever text derived from the current folder will leave the user's device. Placeholders are INTENTIONAL and must be preserved in outbound payloads; do not rehydrate them.
---

# redact-outbound — Placeholder handling rules

## Why placeholders exist

Piighost replaces PII with opaque tokens before any text reaches the model context. The real values are stored encrypted in a local vault. This means the model's working context is already safe to send to Anthropic's API — but drafts the user writes *back* out (replies, documents, external tool calls) must keep placeholders intact so nothing sensitive leaves the device.

## Placeholder format

```
«<LABEL>_<NNN>»      example: «PER_001», «ORG_014», «IBAN_003», «EMAIL_007»
```

- Always three digits, zero-padded.
- The label vocabulary: `PER`, `ORG`, `LOC`, `EMAIL`, `PHONE`, `IBAN`, `SIREN`, `NIR`, `DATE_DOB`. Other labels may appear — treat any `«LABEL_NNN»` pattern as a placeholder.
- Deterministic per `(project, real_value)`: the same IBAN always becomes the same `«IBAN_NNN»` within one project.

## Rules when drafting outbound content

1. **Keep placeholders verbatim.** Do not remove them. Do not prefix them (*"Mr. «PER_001»"* is wrong — the placeholder already represents the full personal reference).
2. **Do not rehydrate for outbound.** If you need to show the user a real value on their screen (not in an outbound payload), call `mcp__hacienda__rehydrate_text` on the preview string only. The outbound payload keeps the placeholder.
3. **If the user types a real name in chat**, call `mcp__hacienda__anonymize_text` on any text you incorporate into an outbound draft, including the user's words, before sending.
4. **For every outbound tool call**, append a `session_audit_append` event with `event="outbound"`, `payload={"tool": <name>, "n_placeholders": <count>}`. Never include the raw payload text in the audit.

## Tools that count as "outbound"

Any of:
- `Write`, `Edit`, `MultiEdit` when writing outside the Cowork folder
- `WebFetch`, `WebSearch`
- Any MCP tool whose name contains `slack`, `gmail`, `email`, `mail`, `drive`, `docusign`, `sign`, `webhook`, `post`

When in doubt, treat the tool as outbound.

## Example

User: *"Reply to Jean Martin's email from Monday saying we'll send the contract by Friday."*

Your draft outbound payload:
```
Cher «PER_001»,

Merci pour votre email. Nous vous transmettrons le contrat d'ici vendredi.

Cordialement,
```

The `To:` field uses a placeholder email (`«EMAIL_007»`) pulled from the original email, not a raw address.

When the user reads the draft in Cowork, the plugin may rehydrate `«PER_001»` → `Jean Martin` for display only. The actual outbound tool call carries the placeholder.
````

- [ ] **Step 2: Commit**

```bash
git add skills/redact-outbound/SKILL.md
git commit -m "feat(skills): redact-outbound — placeholder handling rules"
```

---

## Task 16: `CONNECTORS.md`

- [ ] **Step 1: Write**

````markdown
# Connectors

## How tool references work

Hacienda ships with one MCP server: **piighost** (local, stdio-launched, aliased as `hacienda`). It provides retrieval, anonymisation, vault access, and auditing.

Plugin skills also reference generic categories (`~~cloud storage`, `~~email`) when drafting outbound content — these are fulfilled by whatever additional MCP servers the user has configured in Claude Desktop (Box, Egnyte, Gmail, Microsoft 365, etc.). Hacienda is tool-agnostic for outbound: it does not bundle connector MCP servers.

## Connectors for this plugin

| Category | Placeholder | Bundled with hacienda | User-provided options |
|----------|-------------|-----------------------|----------------------|
| Retrieval & PII | `~~retrieval` | **piighost** (required) | — |
| Cloud storage | `~~cloud storage` | — | Box, Egnyte, Dropbox, SharePoint, Google Drive |
| Email | `~~email` | — | Gmail, Microsoft 365 |
| Chat | `~~chat` | — | Slack, Microsoft Teams |
| E-signature | `~~e-signature` | — | DocuSign, Adobe Sign |
| Calendar | `~~calendar` | — | Google Calendar, Microsoft 365 |

The retrieval connector is mandatory. All outbound connectors are optional — hacienda works with zero of them installed (you just won't be able to send redacted drafts directly from chat).

## Installing piighost

`uvx` handles it automatically on first launch — see `.mcp.json`. If `uvx` is not on your PATH, run once:

```bash
pip install piighost
```

Then Cowork's plugin loader will find it via `python -m piighost`.
````

- [ ] **Step 2: Commit**

```bash
git add CONNECTORS.md
git commit -m "docs: CONNECTORS.md — required + optional MCP servers"
```

---

## Task 17: `README.md`

- [ ] **Step 1: Write**

````markdown
# Hacienda — PII-safe RAG for Claude Desktop

> A Cowork plugin that makes Claude Desktop safe to use under professional secrecy.

**Version:** 0.1.0
**License:** MIT (plugin code) — paid support contracts available separately.
**Target users:** avocats, notaires, experts-comptables, médecins, CGP/CIF, conseils en propriété industrielle — any professional bound by *secret professionnel* (Article 226-13 Code pénal) or equivalent confidentiality duty.

## What it does

- Index a client folder (PDF, DOCX, XLSX, emails, notes) locally.
- Answer questions about the folder with cited sources, never sending raw PII to the cloud.
- Redact outbound drafts (emails, Slack, documents) before they leave the device.
- Audit every redaction round-trip per session.

## Why it exists

Raw Claude Desktop ships prompts and files to Anthropic's US-hosted API. For regulated professionals, that breaks secret professionnel. Hacienda wraps the `piighost` MCP server so every prompt that leaves the laptop has been stripped of identifiable data first — and real values come back locally.

The plugin introduces **zero new code** beyond configuration + prose. All logic lives in piighost.

## Installation

### 1. Install from the marketplace

```
claude plugins add anthropics/marketplace/hacienda
```

(Pending official marketplace listing. Meanwhile: `claude plugins add jamon8888/hacienda`.)

### 2. Install piighost (one time)

```bash
# Recommended — with uv (handles extras automatically):
uvx --from piighost piighost --version

# Or via pip:
pip install piighost
```

### 3. Open a client folder in Cowork

Drag a folder onto the Cowork window, or use **File → Open Folder**. Hacienda automatically indexes it and surfaces a status chip.

## Quick start

```
/index              # force-index the current folder
/ask Who signed the NDA dated 2025-03-12?
/status             # index health
/audit              # session redaction report
```

## How it stays safe

1. **Every retrieval result is already redacted.** Piighost's `query` tool replaces PII with placeholders (`«PER_001»`, `«IBAN_003»`) before text reaches the model.
2. **Drafts keep placeholders outbound.** The `redact-outbound` skill tells the model to preserve placeholders in every outbound tool call.
3. **Real values stay local.** Vault is AES-256-GCM on disk; key is in `~/.hacienda/vault.key` or `CLOAKPIPE_VAULT_KEY` env var.
4. **Per-session audit log.** `~/.hacienda/sessions/<session_id>.audit.jsonl` records every round-trip. `/audit` renders it.

## Limitations — honest list

- **No PreToolUse seatbelt.** Cowork plugins don't ship executable hooks (v1). If the user pastes a raw client name into chat, it's up to the skill prose + model discipline to call `anonymize_text` before sending it outbound. We document this explicitly in `skills/redact-outbound/SKILL.md`.
- **One active folder at a time.** Switching folders switches projects — no cross-folder retrieval in v1.
- **Network drives use a 10-minute poll** for change detection. Filesystem watchers are unreliable on SMB/CIFS.
- **Generic skill pack.** Vertical profiles (notaire-specific, médical, etc.) are a paid-support deliverable.

## Paid support

Contact `support@piighost.example` for:
- Onboarding workshops for firms (half-day, remote)
- Vertical profile packs (notaire, avocat, expert-comptable)
- SLA / priority support contracts
- On-premise deployment

---

# Hacienda — RAG confidentiel pour Claude Desktop

> Un plugin Cowork qui rend Claude Desktop compatible avec le secret professionnel.

**Pour qui :** avocats, notaires, experts-comptables, médecins, CGP/CIF, conseils en propriété industrielle — tout professionnel soumis au secret professionnel (article 226-13 du Code pénal) ou à une obligation équivalente.

## Ce que fait Hacienda

- Indexe localement un dossier client (PDF, DOCX, XLSX, emails, notes).
- Répond à vos questions sur le dossier avec citations, sans jamais envoyer de données identifiables dans le cloud.
- Anonymise les brouillons sortants (emails, Slack, documents) avant tout envoi.
- Trace chaque session : quelles données ont été anonymisées, quels tokens sont sortis, lesquels sont revenus.

## Installation

```
claude plugins add anthropics/marketplace/hacienda
pip install piighost
```

Puis ouvrez un dossier client dans Cowork.

## Commandes

```
/index              # forcer l'indexation
/ask Quelles sont les échéances du contrat SaaS 2024 ?
/status             # état de l'index
/audit              # rapport de session
```

## Support payant

Contacts commerciaux : `support@piighost.example` (workshops d'onboarding, profils métiers, SLA, déploiement on-premise).
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README.md (EN + FR)"
```

---

## Task 18: E2E smoke test + CI gate

**Goal:** End-to-end validation that piighost's MCP surface supports the full hacienda workflow: bootstrap → index a sample folder → query → audit. Lives in the piighost repo so CI runs it on every change.

**Files:**
- Create: `tests/e2e/test_hacienda_cowork_smoke.py`
- Modify: `tests/e2e/conftest.py` — allow the new test when kreuzberg is present (it already is when the `[index]` extra is installed)

- [ ] **Step 1: Write the smoke test**

```python
# tests/e2e/test_hacienda_cowork_smoke.py
"""End-to-end smoke for the hacienda Cowork plugin's MCP surface.

Script form of the skill prose — every MCP call a hacienda skill makes
is executed here against a real in-process piighost service.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from piighost.mcp.server import build_mcp


@pytest.mark.asyncio
async def test_full_hacienda_flow(tmp_path: Path, monkeypatch) -> None:
    # Set up a fake Cowork folder with a single text document.
    folder = tmp_path / "clients" / "ACME"
    folder.mkdir(parents=True)
    (folder / "note.txt").write_text(
        "Contact: Jean Martin, 01 23 45 67 89. Contract signed 2025-03-12.",
        encoding="utf-8",
    )

    monkeypatch.setenv("HACIENDA_DATA_DIR", str(tmp_path / "hdata"))
    monkeypatch.setenv("CLOAKPIPE_VAULT_KEY", "x" * 48)

    mcp, svc = await build_mcp(vault_dir=tmp_path / "vault")
    try:
        # 1. resolve_project_for_folder
        resolve = await mcp.get_tool("resolve_project_for_folder")
        r = (await resolve.run({"folder": str(folder)})).structured_content
        project = r["project"]
        assert project.startswith("acme-")

        # 2. bootstrap_client_folder
        bootstrap = await mcp.get_tool("bootstrap_client_folder")
        b = (await bootstrap.run({"folder": str(folder)})).structured_content
        assert b["project"] == project

        # 3. index_path
        index = await mcp.get_tool("index_path")
        await index.run({
            "path": str(folder),
            "recursive": True,
            "force": False,
            "project": project,
        })

        # 4. per-folder status resource
        b64 = base64.urlsafe_b64encode(str(folder).encode()).decode().rstrip("=")
        resources = await mcp.get_resources()
        template = resources[f"piighost://folders/{{b64_path}}/status"]
        status_payload = json.loads(await template.read({"b64_path": b64}))
        assert status_payload["project"] == project
        assert status_payload["state"] in {"ready", "empty"}

        # 5. query
        query = await mcp.get_tool("query")
        q = (await query.run({
            "text": "When was the contract signed?",
            "k": 5,
            "project": project,
            "rerank": False,
        })).structured_content
        excerpts = q.get("results") or q.get("excerpts") or []
        assert excerpts, "expected at least one hit for the indexed note"

        # 6. audit round-trip
        append = await mcp.get_tool("session_audit_append")
        await append.run({
            "session_id": "e2e-1",
            "event": "query",
            "payload": {"n_excerpts": len(excerpts), "project": project},
        })
        read = await mcp.get_tool("session_audit_read")
        events = (await read.run({"session_id": "e2e-1"})).structured_content
        if isinstance(events, dict) and "result" in events:
            events = events["result"]
        assert len(events) == 1
        assert events[0]["event"] == "query"
        # Safety invariant: audit payload must not contain raw PII
        assert "Jean Martin" not in json.dumps(events[0])
    finally:
        await svc.close()
```

- [ ] **Step 2: Add the new file to the e2e collect-ignore gate**

Edit `tests/e2e/conftest.py` so slim CI environments (no kreuzberg) skip it cleanly:

```python
    collect_ignore = [
        "test_haystack_rag_advanced.py",
        "test_haystack_rag_roundtrip.py",
        "test_hacienda_cowork_smoke.py",  # NEW
        "test_incremental_indexing.py",
        "test_index_query_roundtrip.py",
        "test_langchain_rag_advanced.py",
        "test_langchain_rag_roundtrip.py",
        "test_project_isolation.py",
    ]
```

- [ ] **Step 3: Run the smoke test in WSL (kreuzberg required)**

```bash
wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-mcp && uv run pytest tests/e2e/test_hacienda_cowork_smoke.py -v"
```

Expected: 1 passed. If the `query` tool's result shape differs (`.results` vs `.excerpts`), adjust the test to match the actual schema (the test accepts both keys).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_hacienda_cowork_smoke.py tests/e2e/conftest.py
git commit -m "test(e2e): hacienda Cowork plugin smoke — full bootstrap/index/query/audit flow"
```

---

## Task 19: Marketplace metadata + release tag

- [ ] **Step 1: Bump plugin version and add marketplace hints**

Update `hacienda/.claude-plugin/plugin.json`:

```json
{
  "name": "hacienda",
  "version": "0.1.0",
  "description": "PII-safe RAG over your client folders, directly inside Claude Desktop. Built for regulated professionals (avocats, notaires, experts-comptables, médecins) bound by professional secrecy. Indexes folders locally, redacts outbound requests, cites sources.",
  "author": {
    "name": "piighost team",
    "url": "https://github.com/jamon8888/hacienda"
  },
  "homepage": "https://github.com/jamon8888/hacienda",
  "repository": "https://github.com/jamon8888/hacienda",
  "keywords": ["rag", "pii", "gdpr", "cowork", "legal", "secret-professionnel", "french"],
  "license": "MIT"
}
```

> **Open question:** the official marketplace may require additional fields (screenshots, icon path, long description). The `legal/plugin.json` reference has only `name, version, description, author.name`. If Anthropic's marketplace submission asks for more, add them here before submission. Do NOT invent fields speculatively.

- [ ] **Step 2: Tag the initial release**

```bash
cd /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-plugin
git tag -a v0.1.0 -m "hacienda v0.1.0 — initial Cowork marketplace release"
```

- [ ] **Step 3: Commit metadata changes**

```bash
git add .claude-plugin/plugin.json
git commit -m "chore: enrich plugin.json with repo/homepage/keywords for marketplace"
```

- [ ] **Step 4: Push when the hacienda GitHub repo exists**

```bash
# After `gh repo create jamon8888/hacienda --public`:
git remote add origin git@github.com:jamon8888/hacienda.git
git push -u origin main
git push --tags
```

---

## Final checks

Before declaring done:

- [ ] `uv run pytest` passes in piighost.
- [ ] The hacienda plugin directory passes `claude plugins install --local <path>` (manual Cowork check on the dev machine).
- [ ] Opening a test folder in Cowork surfaces the status chip from `piighost://folders/{b64}/status`.
- [ ] `/ask`, `/index`, `/status`, `/audit` all appear in the slash-command palette.
- [ ] `/ask` returns a cited answer over a test folder.
- [ ] `/audit` shows at least one `query` event after a round-trip.
- [ ] `~/.hacienda/sessions/` contains JSONL files, and `grep -Ri "Jean Martin" ~/.hacienda/` returns zero hits.

---

## Self-Review

**Spec coverage:** every spec §4 in-scope item has a home — `knowledge-base` skill (§4), `/index` + `/status` + `/audit` (§4 commands), redacted-transit (§6, via piighost's existing `anonymize_text`/`rehydrate_text`), status resource (§5.4.4), first-run bootstrap (§5.4.6, relocated from `bin/` to MCP tool), localization (§7, via README.md EN+FR and skill descriptions), MIT license + paid support (§9). The spec §4 items now correctly located:

- ❌ Plugin-side hooks (§4, §5.4.3): **removed** — replaced by skill-prose discipline documented honestly in README "Limitations".
- ❌ Plugin-side agents (§5.4, agents/): **removed** — no agent primitive in the Cowork reference.
- ❌ Plugin-side monitors (§4, monitors/): **removed** — no monitor primitive in the reference. Status is a polled resource.
- ❌ Vendored piighost (§5.2): **removed** — piighost installs as a normal package; `uvx` handles it.
- ✅ Everything else: present.

**Placeholder scan:** none found. Open questions are explicitly labelled ("Verification gap", "Open question") and have a Task where they'll be resolved (18 for CLI flags, 19 for marketplace fields).

**Type consistency:** `resolve_project_for_folder` returns `{folder, project}` — same keys in Tasks 3, 5, 10, 12, 13, 18. Audit events are `{timestamp, event, payload}` — same in Tasks 6, 14, 18. `bootstrap_client_folder` returns `{folder, project, data_dir, vault_key_provisioned}` — same in Tasks 7, 10.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-21-hacienda-cowork-plugin.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

**Which approach?**
