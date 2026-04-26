# Interactive Install Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `piighost install --mode=light|strict` + env-var-driven shell scripts with an interactive Python flow built around two named modes (`Full`, `MCP-only`), backed by an `InstallPlan` dataclass that both interactive prompts and CLI flags produce, executed by a thin walker that delegates to existing mode runners.

**Architecture:** Producers (`interactive.py` + `flags.py`) build an `InstallPlan` (frozen dataclass). The `executor.py` walks it linearly and calls focused helpers in `modes.py`, `clients.py`, `service/user_service.py`, `models.py`. Two new CLI commands (`piighost connect`, `piighost disconnect`) construct mini plans and reuse the same executor. Existing `_run_light_mode` / `_run_strict_mode` are preserved — they become the proxy-setup backends the executor calls.

**Tech Stack:** Python 3.10+, typer (existing CLI framework), rich (already a transitive dep, used for prompts), pydantic v2 (existing), pytest, stdlib only for the user-level service helpers (subprocess, plistlib for macOS, no new deps). The plan adds zero new top-level dependencies.

**Spec:** [docs/superpowers/specs/2026-04-26-interactive-install-redesign.md](../specs/2026-04-26-interactive-install-redesign.md)

**Worktree:** Engineer should run `superpowers:using-git-worktrees` to create an isolated worktree before starting. All work targets a single feature branch (e.g. `feat/interactive-install`).

---

## File Map

### New files

| Path | Purpose |
|------|---------|
| `src/piighost/install/plan.py` | `InstallPlan` dataclass + `Mode`/`Embedder`/`Client` StrEnums |
| `src/piighost/install/flags.py` | CLI flag parsing → `InstallPlan`; deprecation aliases |
| `src/piighost/install/interactive.py` | Rich-driven prompts → `InstallPlan` |
| `src/piighost/install/executor.py` | Walks an `InstallPlan`, runs each step |
| `src/piighost/install/modes.py` | `run_light_mode_proxy()` / `run_strict_mode_proxy()` / `run_mcp_only()` — thin wrappers over existing `_run_light_mode` / `_run_strict_mode` |
| `src/piighost/install/clients.py` | Detect Claude Code + Desktop; register/unregister the MCP entry and BASE_URL |
| `src/piighost/install/recovery.py` | `connect()` / `disconnect()` — build mini `InstallPlan`s, call executor |
| `src/piighost/install/service/user_service.py` | Per-platform user-level auto-restart (LaunchAgent / systemd `--user` / Win schtasks `/onlogon`) |
| `src/piighost/cli/commands/connect.py` | `piighost connect` typer command |
| `src/piighost/cli/commands/disconnect.py` | `piighost disconnect` typer command |
| `scripts/check_mcpb_consistency.py` | CI helper: assert bundle versions match `pyproject.toml` |
| `docs/install-paths.md` | User-facing comparison of install script vs MCPB |
| `tests/install/test_plan.py` | Unit tests for `InstallPlan` validation + `describe()` |
| `tests/install/test_flags.py` | Unit tests for flag parsing + deprecation warnings |
| `tests/install/test_clients.py` | Unit tests for client detection + registration with tmp HOME |
| `tests/install/test_user_service_darwin.py` | macOS user-service unit tests (subprocess mocked) |
| `tests/install/test_user_service_linux.py` | Linux user-service unit tests |
| `tests/install/test_user_service_windows.py` | Windows user-service unit tests |
| `tests/install/test_recovery.py` | Unit tests for connect/disconnect |
| `tests/install/test_modes.py` | Unit tests for the three mode runners |
| `tests/install/test_executor.py` | Unit tests for executor with monkeypatched modules |
| `tests/install/test_interactive.py` | Unit tests for interactive prompts (mocked rich Console) |
| `tests/install/test_install_e2e.py` | End-to-end test of `piighost install` for each mode |

### Modified files

| Path | Change |
|------|--------|
| `src/piighost/install/__init__.py` | Replaces the legacy `run()` body with a thin dispatch: `flags.parse()` → `InstallPlan` (interactive if TTY) → `executor.execute(plan)`. Keeps `_run_light_mode` / `_run_strict_mode` as private functions called by `modes.py`. |
| `src/piighost/cli/main.py` | Wire `connect`/`disconnect` typer commands; extend `doctor` command help reference. |
| `src/piighost/cli/commands/doctor.py` | Add proxy-reachability check + self-heal hint. |
| `scripts/install.sh` | Default `MODE=full` (was `strict`); same `EXTRAS=proxy,mcp,index,gliner2,cache`. Updated banner copy. |
| `scripts/install.ps1` | Same updates as `install.sh`. |
| `tests/unit/install/test_install_cmd.py` | Adapt to new flag set; legacy `--mode=light/strict` deprecation tests added. |

### Files preserved untouched

`src/piighost/install/{ca.py, claude_config.py, host_config.py, docker.py, models.py, preflight.py, ui.py, uv_path.py, hosts_file.py}`, `src/piighost/install/trust_store/`, `src/piighost/install/service/{darwin.py, linux.py, windows.py, __init__.py}`, `bundles/{core,full}/`, `scripts/build_mcpb.py`.

---

## Build order rationale

Build bottom-up: data structures first, then producers, then executor, then CLI integration, then migration. Each task ships a green test before moving on.

1. **Plan dataclass** — pure types, no I/O. Foundation.
2. **Flags parser** — produces a plan from argv. No I/O.
3. **Clients module** — detection + register/unregister. Tested with tmp HOME.
4–6. **User-service per platform** — Linux first (smallest blast radius), then macOS, then Windows.
7. **Recovery commands** — depend on `clients`. Standalone CLI.
8. **Modes** — wraps existing runners. Cheap.
9. **Executor** — depends on all of the above; tested with monkeypatched modules.
10. **Interactive prompts** — depends on `plan` + `clients` (for detection); tests with mocked rich Console.
11. **Wire connect/disconnect into CLI**.
12. **Rewrite `install/__init__.py`** — wires producers into executor; e2e test.
13. **Extend `doctor`** — reachability check.
14. **Update shell scripts** — defaults flip to `full`.
15. **MCPB sanity** — `check_mcpb_consistency.py` + verify build still works.
16. **Docs page** — `install-paths.md`.

---

### Task 1: `InstallPlan` dataclass

**Files:**
- Create: `src/piighost/install/plan.py`
- Test: `tests/install/test_plan.py`

- [ ] **Step 1.1: Write the failing test for the dataclass and validation rules**

```python
# tests/install/test_plan.py
from __future__ import annotations

from pathlib import Path

import pytest

from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _base_kwargs(**overrides):
    base = dict(
        mode=Mode.FULL,
        vault_dir=Path("/tmp/vault"),
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=frozenset({Client.CLAUDE_CODE}),
        install_user_service=True,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    base.update(overrides)
    return base


def test_default_full_plan_validates():
    plan = InstallPlan(**_base_kwargs())
    assert plan.mode is Mode.FULL
    assert plan.embedder is Embedder.LOCAL


def test_mistral_without_key_is_rejected():
    with pytest.raises(ValueError, match="mistral_api_key"):
        InstallPlan(**_base_kwargs(embedder=Embedder.MISTRAL, mistral_api_key=None))


def test_mistral_with_key_is_accepted():
    plan = InstallPlan(
        **_base_kwargs(embedder=Embedder.MISTRAL, mistral_api_key="sk-test")
    )
    assert plan.mistral_api_key == "sk-test"


def test_mcp_only_with_user_service_is_rejected():
    with pytest.raises(ValueError, match="mcp-only"):
        InstallPlan(**_base_kwargs(mode=Mode.MCP_ONLY, install_user_service=True))


def test_mcp_only_without_user_service_is_accepted():
    plan = InstallPlan(
        **_base_kwargs(mode=Mode.MCP_ONLY, install_user_service=False)
    )
    assert plan.mode is Mode.MCP_ONLY


def test_strict_without_user_service_is_rejected():
    with pytest.raises(ValueError, match="strict"):
        InstallPlan(**_base_kwargs(mode=Mode.STRICT, install_user_service=False))


def test_describe_lists_each_step():
    plan = InstallPlan(**_base_kwargs())
    out = plan.describe()
    assert "CA + leaf cert" in out
    assert "Claude Code" in out
    assert "auto-restart" in out
    assert "/tmp/vault" in out
    assert "local" in out


def test_describe_skips_proxy_lines_in_mcp_only():
    plan = InstallPlan(
        **_base_kwargs(
            mode=Mode.MCP_ONLY, install_user_service=False
        )
    )
    out = plan.describe()
    assert "CA" not in out
    assert "auto-restart" not in out


def test_describe_warns_when_embedder_is_none():
    plan = InstallPlan(**_base_kwargs(embedder=Embedder.NONE))
    out = plan.describe()
    assert "RAG indexing/query disabled" in out
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `pytest tests/install/test_plan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'piighost.install.plan'`

- [ ] **Step 1.3: Write the implementation**

```python
# src/piighost/install/plan.py
"""InstallPlan dataclass + supporting StrEnums.

The plan is a pure-data record of what `piighost install` will do.
Both the interactive prompts (`interactive.py`) and the CLI flag
parser (`flags.py`) produce one; the executor (`executor.py`) reads
one and walks it linearly.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Mode(StrEnum):
    """Top-level install mode.

    `--mode=light` is NOT a value here. It is mapped to `FULL` by
    `flags.py` after printing a deprecation warning.
    """

    FULL = "full"           # light proxy + MCP + RAG (interactive default)
    MCP_ONLY = "mcp-only"   # MCP + RAG, no proxy
    STRICT = "strict"       # legacy: system-wide proxy (not in menu)


class Embedder(StrEnum):
    LOCAL = "local"      # ~500 MB sentence-transformers download
    MISTRAL = "mistral"  # remote API, needs MISTRAL_API_KEY
    NONE = "none"        # skip RAG embedding


class Client(StrEnum):
    CLAUDE_CODE = "code"
    CLAUDE_DESKTOP = "desktop"


@dataclass(frozen=True)
class InstallPlan:
    """Frozen description of an install run.

    Validation runs in `__post_init__`; bad combinations raise
    `ValueError` so producers can surface clear messages.
    """

    mode: Mode
    vault_dir: Path
    embedder: Embedder
    mistral_api_key: str | None
    clients: frozenset[Client]
    install_user_service: bool
    warmup_models: bool
    force: bool
    dry_run: bool

    def __post_init__(self) -> None:
        if self.embedder is Embedder.MISTRAL and not self.mistral_api_key:
            raise ValueError(
                "embedder=mistral requires mistral_api_key (pass --mistral-api-key "
                "or set the MISTRAL_API_KEY env var)."
            )
        if self.mode is Mode.MCP_ONLY and self.install_user_service:
            raise ValueError(
                "install_user_service has no effect in mcp-only mode "
                "(no proxy daemon to restart)."
            )
        if self.mode is Mode.STRICT and not self.install_user_service:
            raise ValueError(
                "strict mode needs the auto-restart service "
                "(remove --no-user-service or pick a different mode)."
            )

    def describe(self) -> str:
        """Bullet-list rendering for --dry-run and the closing review."""
        lines: list[str] = []
        if self.mode in (Mode.FULL, Mode.STRICT):
            lines.append("  • Generate CA + leaf cert at ~/.piighost/proxy/")
        if self.mode is Mode.STRICT:
            lines.append("  • Add 127.0.0.1 api.anthropic.com to hosts file (sudo)")
            lines.append("  • Install system-level background service on :443 (sudo)")
        if self.clients:
            client_names = ", ".join(self._client_label(c) for c in sorted(self.clients))
            lines.append(f"  • Register MCP server in {client_names}")
        if self.mode is Mode.FULL and Client.CLAUDE_CODE in self.clients:
            lines.append("  • Set ANTHROPIC_BASE_URL=https://localhost:8443 for Claude Code")
        if self.install_user_service:
            lines.append("  • Install user-level auto-restart service")
        lines.append(f"  • Vault: {self.vault_dir}")
        if self.embedder is Embedder.NONE:
            lines.append(
                "  • Embedder: none (RAG indexing/query disabled until you "
                "run `piighost config set embedder ...`)"
            )
        else:
            embedder_note = {
                Embedder.LOCAL: "local (~500 MB download)",
                Embedder.MISTRAL: "Mistral API",
            }[self.embedder]
            lines.append(f"  • Embedder: {embedder_note}")
        if self.warmup_models:
            lines.append("  • Download model weights now")
        return "\n".join(lines)

    @staticmethod
    def _client_label(c: Client) -> str:
        return {Client.CLAUDE_CODE: "Claude Code", Client.CLAUDE_DESKTOP: "Claude Desktop"}[c]
```

- [ ] **Step 1.4: Run test to verify all pass**

Run: `pytest tests/install/test_plan.py -v`
Expected: 8 passed.

- [ ] **Step 1.5: Commit**

```bash
git add src/piighost/install/plan.py tests/install/test_plan.py
git commit -m "feat(install): InstallPlan dataclass + StrEnums"
```

---

### Task 2: `flags.py` — CLI flags → InstallPlan

**Files:**
- Create: `src/piighost/install/flags.py`
- Test: `tests/install/test_flags.py`

- [ ] **Step 2.1: Write the failing test**

```python
# tests/install/test_flags.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

from piighost.install.flags import (
    DeprecationNotice,
    FlagsResult,
    parse_flags,
)
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def test_minimal_full_flags():
    res = parse_flags(
        mode="full",
        vault_dir=None,
        embedder=None,
        mistral_api_key=None,
        clients=None,
        user_service=None,
        warmup=False,
        force=False,
        dry_run=False,
        yes=True,
        env={},
    )
    assert isinstance(res.plan, InstallPlan)
    assert res.plan.mode is Mode.FULL
    assert res.plan.embedder is Embedder.LOCAL
    assert res.plan.vault_dir == Path.home() / ".piighost" / "vault"
    assert res.plan.install_user_service is True
    assert res.deprecations == []


def test_mcp_only_defaults_user_service_off():
    res = parse_flags(
        mode="mcp-only", vault_dir=None, embedder=None,
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True, env={},
    )
    assert res.plan.mode is Mode.MCP_ONLY
    assert res.plan.install_user_service is False


def test_light_alias_emits_deprecation_and_maps_to_full():
    res = parse_flags(
        mode="light", vault_dir=None, embedder=None,
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True, env={},
    )
    assert res.plan.mode is Mode.FULL
    assert any(d.flag == "--mode=light" for d in res.deprecations)


def test_strict_warns_advanced():
    res = parse_flags(
        mode="strict", vault_dir=None, embedder=None,
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True, env={},
    )
    assert res.plan.mode is Mode.STRICT
    assert res.plan.install_user_service is True
    assert any(d.severity == "advanced" for d in res.deprecations)


def test_mistral_without_key_uses_env_var():
    res = parse_flags(
        mode="full", vault_dir=None, embedder="mistral",
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True,
        env={"MISTRAL_API_KEY": "sk-env"},
    )
    assert res.plan.mistral_api_key == "sk-env"


def test_mistral_without_key_or_env_raises():
    with pytest.raises(ValueError, match="mistral_api_key"):
        parse_flags(
            mode="full", vault_dir=None, embedder="mistral",
            mistral_api_key=None, clients=None, user_service=None,
            warmup=False, force=False, dry_run=False, yes=True, env={},
        )


def test_clients_csv_parsed():
    res = parse_flags(
        mode="full", vault_dir=None, embedder=None,
        mistral_api_key=None, clients="code,desktop",
        user_service=None, warmup=False, force=False,
        dry_run=False, yes=True, env={},
    )
    assert res.plan.clients == frozenset({Client.CLAUDE_CODE, Client.CLAUDE_DESKTOP})


def test_unknown_client_name_raises():
    with pytest.raises(ValueError, match="unknown client"):
        parse_flags(
            mode="full", vault_dir=None, embedder=None,
            mistral_api_key=None, clients="code,zoom",
            user_service=None, warmup=False, force=False,
            dry_run=False, yes=True, env={},
        )


def test_strict_with_no_user_service_raises():
    with pytest.raises(ValueError, match="strict"):
        parse_flags(
            mode="strict", vault_dir=None, embedder=None,
            mistral_api_key=None, clients=None, user_service=False,
            warmup=False, force=False, dry_run=False, yes=True, env={},
        )


def test_explicit_vault_dir_honored(tmp_path):
    res = parse_flags(
        mode="full", vault_dir=tmp_path, embedder=None,
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True, env={},
    )
    assert res.plan.vault_dir == tmp_path
```

- [ ] **Step 2.2: Run the test to verify it fails**

Run: `pytest tests/install/test_flags.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'piighost.install.flags'`.

- [ ] **Step 2.3: Implement flags.py**

```python
# src/piighost/install/flags.py
"""Parse CLI flags / env vars into an InstallPlan.

This module is the non-interactive producer. It is also called by
the interactive flow when the user has supplied any explicit flags
(in which case those flags become defaults that the prompts may
still override).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from piighost.install.clients import detect_all
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


@dataclass(frozen=True)
class DeprecationNotice:
    flag: str
    severity: Literal["deprecated", "advanced"]
    message: str


@dataclass(frozen=True)
class FlagsResult:
    plan: InstallPlan
    deprecations: list[DeprecationNotice]


_VALID_CLIENTS = {c.value: c for c in Client}


def parse_flags(
    *,
    mode: str | None,
    vault_dir: Path | None,
    embedder: str | None,
    mistral_api_key: str | None,
    clients: str | None,
    user_service: bool | None,
    warmup: bool,
    force: bool,
    dry_run: bool,
    yes: bool,
    env: dict[str, str],
) -> FlagsResult:
    """Pure function: arguments → InstallPlan + deprecation notices.

    Defaults applied here so producers (CLI, interactive) share one
    set of rules. The caller is responsible for printing the
    deprecation notices to the user.
    """
    deprecations: list[DeprecationNotice] = []

    resolved_mode, mode_deprecation = _resolve_mode(mode)
    if mode_deprecation is not None:
        deprecations.append(mode_deprecation)

    resolved_embedder = _resolve_embedder(embedder)
    resolved_key = mistral_api_key or env.get("MISTRAL_API_KEY") or None
    if resolved_embedder is Embedder.MISTRAL and not resolved_key:
        raise ValueError(
            "embedder=mistral requires mistral_api_key "
            "(pass --mistral-api-key or set MISTRAL_API_KEY env var)."
        )

    resolved_clients = _resolve_clients(clients)
    resolved_vault = vault_dir or (Path.home() / ".piighost" / "vault")

    if user_service is None:
        # Default: on for FULL/STRICT, off for MCP_ONLY
        resolved_user_service = resolved_mode is not Mode.MCP_ONLY
    else:
        resolved_user_service = user_service

    if resolved_mode is Mode.STRICT and not resolved_user_service:
        raise ValueError(
            "strict mode requires the auto-restart service. "
            "Remove --no-user-service or pick --mode=full."
        )

    plan = InstallPlan(
        mode=resolved_mode,
        vault_dir=resolved_vault,
        embedder=resolved_embedder,
        mistral_api_key=resolved_key,
        clients=resolved_clients,
        install_user_service=resolved_user_service,
        warmup_models=warmup,
        force=force,
        dry_run=dry_run,
    )
    return FlagsResult(plan=plan, deprecations=deprecations)


def _resolve_mode(raw: str | None) -> tuple[Mode, DeprecationNotice | None]:
    if raw is None:
        return Mode.FULL, None
    if raw == "light":
        return Mode.FULL, DeprecationNotice(
            flag="--mode=light",
            severity="deprecated",
            message=(
                "[deprecated] --mode=light is now '--mode=full'. "
                "This alias will be removed in 0.10.0."
            ),
        )
    if raw == "strict":
        return Mode.STRICT, DeprecationNotice(
            flag="--mode=strict",
            severity="advanced",
            message=(
                "[advanced] strict mode requires admin and modifies your "
                "hosts file. Most users want '--mode=full'. See "
                "docs/install-paths.md."
            ),
        )
    if raw == "full":
        return Mode.FULL, None
    if raw == "mcp-only":
        return Mode.MCP_ONLY, None
    raise ValueError(
        f"unknown mode {raw!r}. Valid: full, mcp-only, strict, light (deprecated)."
    )


def _resolve_embedder(raw: str | None) -> Embedder:
    if raw is None:
        return Embedder.LOCAL
    try:
        return Embedder(raw)
    except ValueError as exc:
        raise ValueError(
            f"unknown embedder {raw!r}. Valid: local, mistral, none."
        ) from exc


def _resolve_clients(raw: str | None) -> frozenset[Client]:
    if raw is None:
        # Auto-detect: include any client whose config dir already exists
        return frozenset(loc.client for loc in detect_all() if loc.exists)
    out: set[Client] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token not in _VALID_CLIENTS:
            raise ValueError(
                f"unknown client {token!r}. Valid: "
                + ", ".join(sorted(_VALID_CLIENTS))
            )
        out.add(_VALID_CLIENTS[token])
    return frozenset(out)
```

- [ ] **Step 2.4: Note the forward dependency on `clients.detect_all`**

`flags.py` imports `detect_all` from `clients.py` (Task 3). Tests in this task pass `clients="code,desktop"` to avoid invoking the auto-detect path until Task 3 lands. The default-clients case is exercised in Task 3's tests.

- [ ] **Step 2.5: Add a stub `clients.detect_all` so `flags.py` imports cleanly**

```python
# src/piighost/install/clients.py  (stub — fully implemented in Task 3)
"""Detect installed Claude clients and register the MCP server.

Stub for Task 2 import-time satisfaction. Real implementation in Task 3.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from piighost.install.plan import Client


@dataclass(frozen=True)
class ClientLocation:
    client: Client
    config_path: Path
    exists: bool


def detect_all() -> list[ClientLocation]:
    return []
```

- [ ] **Step 2.6: Run the test to verify it passes**

Run: `pytest tests/install/test_flags.py -v`
Expected: 10 passed.

- [ ] **Step 2.7: Commit**

```bash
git add src/piighost/install/flags.py src/piighost/install/clients.py \
        tests/install/test_flags.py
git commit -m "feat(install): flag parser + clients stub"
```

---

### Task 3: `clients.py` — detection + register/unregister

**Files:**
- Modify: `src/piighost/install/clients.py` (replace stub)
- Test: `tests/install/test_clients.py`

- [ ] **Step 3.1: Write the failing test**

```python
# tests/install/test_clients.py
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from piighost.install.clients import (
    ClientLocation,
    detect_all,
    register,
    unregister,
)
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _plan(tmp_path: Path, **overrides) -> InstallPlan:
    base = dict(
        mode=Mode.FULL,
        vault_dir=tmp_path / "vault",
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=frozenset({Client.CLAUDE_CODE}),
        install_user_service=True,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    base.update(overrides)
    return InstallPlan(**base)


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def test_detect_all_returns_both_clients(isolated_home):
    locs = {loc.client: loc for loc in detect_all()}
    assert Client.CLAUDE_CODE in locs
    assert Client.CLAUDE_DESKTOP in locs
    for loc in locs.values():
        assert isinstance(loc, ClientLocation)
        assert loc.exists is False  # nothing pre-existing


def test_detect_all_marks_existing_config(isolated_home):
    code_settings = isolated_home / ".claude" / "settings.json"
    code_settings.parent.mkdir(parents=True)
    code_settings.write_text("{}")
    found = {loc.client: loc.exists for loc in detect_all()}
    assert found[Client.CLAUDE_CODE] is True
    assert found[Client.CLAUDE_DESKTOP] is False


def test_register_writes_mcp_entry_and_base_url_for_claude_code(isolated_home):
    plan = _plan(isolated_home, mode=Mode.FULL)
    register(plan, Client.CLAUDE_CODE)
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "mcpServers" in settings
    assert "piighost" in settings["mcpServers"]
    assert settings["mcpServers"]["piighost"]["command"] == "uvx"
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"


def test_register_in_mcp_only_mode_skips_base_url(isolated_home):
    plan = _plan(
        isolated_home, mode=Mode.MCP_ONLY, install_user_service=False
    )
    register(plan, Client.CLAUDE_CODE)
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "piighost" in settings["mcpServers"]
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_register_creates_backup_on_first_write(isolated_home):
    code_settings = isolated_home / ".claude" / "settings.json"
    code_settings.parent.mkdir(parents=True)
    code_settings.write_text(json.dumps({"keep_me": "yes"}))
    plan = _plan(isolated_home)
    register(plan, Client.CLAUDE_CODE)
    bak = code_settings.with_suffix(".json.piighost.bak")
    assert bak.exists()
    assert json.loads(bak.read_text()) == {"keep_me": "yes"}


def test_register_is_idempotent(isolated_home):
    plan = _plan(isolated_home)
    register(plan, Client.CLAUDE_CODE)
    register(plan, Client.CLAUDE_CODE)  # same plan, second time
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    # Backup file should not have been overwritten on second call
    bak = (isolated_home / ".claude" / "settings.json.piighost.bak")
    # bak existed only after first call; content of settings.json now matches
    # the registered shape regardless of how many times we ran.
    assert settings["mcpServers"]["piighost"]["command"] == "uvx"


def test_register_conflict_without_force_raises(isolated_home):
    code_settings = isolated_home / ".claude" / "settings.json"
    code_settings.parent.mkdir(parents=True)
    code_settings.write_text(json.dumps({
        "mcpServers": {
            "piighost": {"command": "different", "args": []}
        }
    }))
    plan = _plan(isolated_home)
    with pytest.raises(RuntimeError, match="conflict"):
        register(plan, Client.CLAUDE_CODE)


def test_register_conflict_with_force_overwrites(isolated_home):
    code_settings = isolated_home / ".claude" / "settings.json"
    code_settings.parent.mkdir(parents=True)
    code_settings.write_text(json.dumps({
        "mcpServers": {
            "piighost": {"command": "different", "args": []}
        }
    }))
    plan = _plan(isolated_home, force=True)
    register(plan, Client.CLAUDE_CODE)
    settings = json.loads(code_settings.read_text())
    assert settings["mcpServers"]["piighost"]["command"] == "uvx"


def test_unregister_removes_only_requested_pieces(isolated_home):
    plan = _plan(isolated_home)
    register(plan, Client.CLAUDE_CODE)
    unregister(Client.CLAUDE_CODE, remove_base_url=True, remove_mcp=False)
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "piighost" in settings["mcpServers"]
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_unregister_no_op_when_config_missing(isolated_home):
    # Should not raise
    unregister(Client.CLAUDE_CODE, remove_base_url=True, remove_mcp=True)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS path")
def test_detect_claude_desktop_macos(isolated_home):
    desktop = (
        isolated_home
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json"
    )
    desktop.parent.mkdir(parents=True)
    desktop.write_text("{}")
    found = {loc.client: loc.exists for loc in detect_all()}
    assert found[Client.CLAUDE_DESKTOP] is True
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `pytest tests/install/test_clients.py -v`
Expected: failures (functions/behavior missing).

- [ ] **Step 3.3: Implement `clients.py`**

```python
# src/piighost/install/clients.py
"""Detect installed Claude clients and register/unregister the
piighost MCP server + ANTHROPIC_BASE_URL env var.

Two clients are supported:
- Claude Code → ~/.claude/settings.json
- Claude Desktop → platform-specific claude_desktop_config.json
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from piighost.install.plan import Client, InstallPlan, Mode


_PROXY_BASE_URL = "https://localhost:8443"
_BACKUP_SUFFIX = ".piighost.bak"


@dataclass(frozen=True)
class ClientLocation:
    client: Client
    config_path: Path
    exists: bool


def claude_code_settings_path() -> Path:
    home = Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or Path.home())
    return home / ".claude" / "settings.json"


def claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return (
            Path(os.environ.get("HOME") or Path.home())
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata is None:
            appdata = str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    return (
        Path(os.environ.get("HOME") or Path.home())
        / ".config"
        / "Claude"
        / "claude_desktop_config.json"
    )


def detect_all() -> list[ClientLocation]:
    code = claude_code_settings_path()
    desktop = claude_desktop_config_path()
    return [
        ClientLocation(client=Client.CLAUDE_CODE, config_path=code, exists=code.exists()),
        ClientLocation(client=Client.CLAUDE_DESKTOP, config_path=desktop, exists=desktop.exists()),
    ]


def _mcp_entry(plan: InstallPlan) -> dict:
    return {
        "command": "uvx",
        "args": [
            "--from",
            "piighost[mcp,index,gliner2,cache]",
            "piighost",
            "serve",
            "--transport",
            "stdio",
        ],
        "env": {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PIIGHOST_VAULT_DIR": str(plan.vault_dir),
        },
    }


def register(plan: InstallPlan, client: Client) -> None:
    """Write the MCP entry (and BASE_URL env, for Claude Code) into the
    client's config file. Idempotent: re-registering with the same plan
    is a no-op."""
    location = _location_for(client)
    config = _read_config(location.config_path)

    desired_entry = _mcp_entry(plan)
    existing = config.get("mcpServers", {}).get("piighost")
    if existing is not None and existing != desired_entry and not plan.force:
        raise RuntimeError(
            f"conflict: mcpServers.piighost in {location.config_path} differs "
            f"from desired entry. Re-run with --force to overwrite."
        )

    if not location.config_path.exists() or not _backup_path(location.config_path).exists():
        if location.config_path.exists():
            _write_backup(location.config_path)

    config.setdefault("mcpServers", {})["piighost"] = desired_entry
    if plan.mode is Mode.FULL and client is Client.CLAUDE_CODE:
        config.setdefault("env", {})["ANTHROPIC_BASE_URL"] = _PROXY_BASE_URL
    _write_config(location.config_path, config)


def unregister(
    client: Client, *, remove_base_url: bool, remove_mcp: bool
) -> None:
    """Remove the requested pieces from the client's config. No-op if
    the config file is missing."""
    location = _location_for(client)
    if not location.config_path.exists():
        return
    config = _read_config(location.config_path)
    if remove_mcp:
        config.get("mcpServers", {}).pop("piighost", None)
    if remove_base_url:
        config.get("env", {}).pop("ANTHROPIC_BASE_URL", None)
    _write_config(location.config_path, config)


def _location_for(client: Client) -> ClientLocation:
    for loc in detect_all():
        if loc.client is client:
            return loc
    raise KeyError(client)


def _read_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + _BACKUP_SUFFIX)


def _write_backup(path: Path) -> None:
    bak = _backup_path(path)
    if bak.exists():
        return
    bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `pytest tests/install/test_clients.py -v`
Expected: 10–11 passed (one `skipif` on non-darwin).

- [ ] **Step 3.5: Re-run flags tests to confirm they still pass with the real `detect_all`**

Run: `pytest tests/install/test_flags.py tests/install/test_plan.py -v`
Expected: 18 passed.

- [ ] **Step 3.6: Commit**

```bash
git add src/piighost/install/clients.py tests/install/test_clients.py
git commit -m "feat(install): client detection + idempotent MCP/BASE_URL writers"
```

---

### Task 4: `service/user_service.py` — Linux user-systemd backend

**Files:**
- Create: `src/piighost/install/service/user_service.py`
- Test: `tests/install/test_user_service_linux.py`

- [ ] **Step 4.1: Write failing Linux test**

```python
# tests/install/test_user_service_linux.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.platform != "linux":
    pytest.skip("linux-only", allow_module_level=True)

from unittest.mock import call, patch

from piighost.install.service.user_service import (
    UserServiceSpec,
    install,
    uninstall,
    status,
)


@pytest.fixture
def spec(tmp_path):
    return UserServiceSpec(
        name="com.piighost.proxy",
        bin_path=Path("/usr/local/bin/piighost"),
        vault_dir=tmp_path / "vault",
        log_dir=tmp_path / "logs",
        listen_port=8443,
    )


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    return tmp_path


def test_install_writes_service_unit(isolated_home, spec):
    with patch("subprocess.run") as run:
        install(spec)
    unit_path = isolated_home / ".config" / "systemd" / "user" / "piighost-proxy.service"
    assert unit_path.exists()
    content = unit_path.read_text()
    assert "ExecStart=/usr/local/bin/piighost serve" in content
    assert "Restart=on-failure" in content
    assert f"PIIGHOST_VAULT_DIR={spec.vault_dir}" in content
    run.assert_any_call(
        ["systemctl", "--user", "daemon-reload"], check=True
    )
    run.assert_any_call(
        ["systemctl", "--user", "enable", "--now", "piighost-proxy.service"], check=True
    )
    run.assert_any_call(
        ["loginctl", "enable-linger", isolated_home.name], check=False
    )


def test_uninstall_disables_and_removes(isolated_home, spec):
    unit_path = isolated_home / ".config" / "systemd" / "user" / "piighost-proxy.service"
    unit_path.parent.mkdir(parents=True)
    unit_path.write_text("placeholder")
    with patch("subprocess.run") as run:
        uninstall(spec)
    assert not unit_path.exists()
    run.assert_any_call(
        ["systemctl", "--user", "disable", "--now", "piighost-proxy.service"], check=False
    )


def test_status_reports_running(isolated_home, spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "active\n"
        result = status(spec)
    assert result == "running"


def test_status_reports_stopped(isolated_home, spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 3
        run.return_value.stdout = "inactive\n"
        result = status(spec)
    assert result == "stopped"
```

- [ ] **Step 4.2: Run to verify failure**

Run: `pytest tests/install/test_user_service_linux.py -v`
Expected: ImportError (`user_service` missing).

- [ ] **Step 4.3: Implement the shared spec + Linux backend**

```python
# src/piighost/install/service/user_service.py
"""Per-platform user-level (no-admin) auto-restart service for the
piighost proxy daemon.

Each platform gets a thin module dispatched on import: macOS uses
LaunchAgent (KeepAlive=true), Linux uses systemd --user, Windows
uses a Scheduled Task with /onlogon trigger.

The Windows path is best-effort — Windows lacks a native unprivileged
KeepAlive analogue. We document the gap rather than paper over it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class UserServiceSpec:
    name: str
    bin_path: Path
    vault_dir: Path
    log_dir: Path
    listen_port: int


# ---- public API ---------------------------------------------------------

def install(spec: UserServiceSpec) -> None:
    _backend().install(spec)


def uninstall(spec: UserServiceSpec) -> None:
    _backend().uninstall(spec)


def status(spec: UserServiceSpec) -> Literal["running", "stopped", "missing"]:
    return _backend().status(spec)


def restart(spec: UserServiceSpec) -> None:
    _backend().restart(spec)


# ---- backend dispatch ---------------------------------------------------

def _backend():
    if sys.platform == "darwin":
        from piighost.install.service import _user_service_darwin
        return _user_service_darwin
    if sys.platform == "win32":
        from piighost.install.service import _user_service_windows
        return _user_service_windows
    from piighost.install.service import _user_service_linux
    return _user_service_linux
```

```python
# src/piighost/install/service/_user_service_linux.py
"""systemd --user backend for the piighost proxy auto-restart service."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from piighost.install.service.user_service import UserServiceSpec

_UNIT_NAME = "piighost-proxy.service"


def _unit_path() -> Path:
    home = Path(os.environ["HOME"])
    base = (
        Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
        / "systemd"
        / "user"
    )
    return base / _UNIT_NAME


def _render(spec: UserServiceSpec) -> str:
    return (
        "[Unit]\n"
        "Description=piighost anonymizing proxy (user)\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={spec.bin_path} serve --listen-port {spec.listen_port}\n"
        "Restart=on-failure\n"
        "RestartSec=5s\n"
        f"Environment=PIIGHOST_VAULT_DIR={spec.vault_dir}\n"
        f"StandardOutput=append:{spec.log_dir / 'proxy.log'}\n"
        f"StandardError=append:{spec.log_dir / 'proxy.log'}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def install(spec: UserServiceSpec) -> None:
    spec.log_dir.mkdir(parents=True, exist_ok=True)
    unit = _unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(_render(spec), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", _UNIT_NAME], check=True
    )
    user = Path(os.environ["HOME"]).name
    subprocess.run(["loginctl", "enable-linger", user], check=False)


def uninstall(spec: UserServiceSpec) -> None:
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", _UNIT_NAME], check=False
    )
    unit = _unit_path()
    if unit.exists():
        unit.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def status(spec: UserServiceSpec) -> str:
    proc = subprocess.run(
        ["systemctl", "--user", "is-active", _UNIT_NAME],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return "running"
    if "inactive" in proc.stdout:
        return "stopped"
    return "missing"


def restart(spec: UserServiceSpec) -> None:
    subprocess.run(
        ["systemctl", "--user", "restart", _UNIT_NAME], check=True
    )
```

- [ ] **Step 4.4: Run Linux tests**

Run: `pytest tests/install/test_user_service_linux.py -v`
Expected: 4 passed (Linux only; skipped elsewhere).

- [ ] **Step 4.5: Commit**

```bash
git add src/piighost/install/service/user_service.py \
        src/piighost/install/service/_user_service_linux.py \
        tests/install/test_user_service_linux.py
git commit -m "feat(install): user-level auto-restart service (linux/systemd --user)"
```

---

### Task 5: `_user_service_darwin.py` — LaunchAgent backend

**Files:**
- Create: `src/piighost/install/service/_user_service_darwin.py`
- Test: `tests/install/test_user_service_darwin.py`

- [ ] **Step 5.1: Write failing macOS test**

```python
# tests/install/test_user_service_darwin.py
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

if sys.platform != "darwin":
    pytest.skip("macos-only", allow_module_level=True)

from unittest.mock import patch

from piighost.install.service.user_service import (
    UserServiceSpec,
    install,
    uninstall,
    status,
)


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def spec(tmp_path):
    return UserServiceSpec(
        name="com.piighost.proxy",
        bin_path=Path("/usr/local/bin/piighost"),
        vault_dir=tmp_path / "vault",
        log_dir=tmp_path / "logs",
        listen_port=8443,
    )


def test_install_writes_plist(isolated_home, spec):
    with patch("subprocess.run") as run:
        install(spec)
    plist_path = isolated_home / "Library" / "LaunchAgents" / "com.piighost.proxy.plist"
    assert plist_path.exists()
    data = plistlib.loads(plist_path.read_bytes())
    assert data["Label"] == "com.piighost.proxy"
    assert data["KeepAlive"] is True
    assert data["ThrottleInterval"] == 10
    assert "/usr/local/bin/piighost" in data["ProgramArguments"]
    run.assert_any_call(["launchctl", "load", "-w", str(plist_path)], check=True)


def test_uninstall_unloads_and_removes(isolated_home, spec):
    plist_path = isolated_home / "Library" / "LaunchAgents" / "com.piighost.proxy.plist"
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(b"<plist></plist>")
    with patch("subprocess.run") as run:
        uninstall(spec)
    assert not plist_path.exists()
    run.assert_any_call(["launchctl", "unload", "-w", str(plist_path)], check=False)


def test_status_reports_running(isolated_home, spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "1234\t0\tcom.piighost.proxy\n"
        result = status(spec)
    assert result == "running"
```

- [ ] **Step 5.2: Verify failure**

Run: `pytest tests/install/test_user_service_darwin.py -v`
Expected: ImportError on `_user_service_darwin`.

- [ ] **Step 5.3: Implement**

```python
# src/piighost/install/service/_user_service_darwin.py
"""LaunchAgent backend (macOS) for piighost proxy auto-restart."""
from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from piighost.install.service.user_service import UserServiceSpec


def _plist_path(spec: UserServiceSpec) -> Path:
    home = Path(os.environ["HOME"])
    return home / "Library" / "LaunchAgents" / f"{spec.name}.plist"


def _render(spec: UserServiceSpec) -> bytes:
    payload = {
        "Label": spec.name,
        "ProgramArguments": [
            str(spec.bin_path),
            "serve",
            "--listen-port",
            str(spec.listen_port),
        ],
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "RunAtLoad": True,
        "StandardOutPath": str(spec.log_dir / "proxy.log"),
        "StandardErrorPath": str(spec.log_dir / "proxy.log"),
        "EnvironmentVariables": {
            "PIIGHOST_VAULT_DIR": str(spec.vault_dir),
        },
    }
    return plistlib.dumps(payload)


def install(spec: UserServiceSpec) -> None:
    spec.log_dir.mkdir(parents=True, exist_ok=True)
    plist = _plist_path(spec)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(_render(spec))
    subprocess.run(["launchctl", "load", "-w", str(plist)], check=True)


def uninstall(spec: UserServiceSpec) -> None:
    plist = _plist_path(spec)
    if plist.exists():
        subprocess.run(
            ["launchctl", "unload", "-w", str(plist)], check=False
        )
        plist.unlink()


def status(spec: UserServiceSpec) -> str:
    proc = subprocess.run(
        ["launchctl", "list", spec.name], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return "missing"
    # Output format: "<pid>\t<status>\t<label>"
    first = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
    pid_field = first.split("\t", 1)[0] if first else "-"
    return "running" if pid_field.isdigit() else "stopped"


def restart(spec: UserServiceSpec) -> None:
    plist = _plist_path(spec)
    subprocess.run(["launchctl", "unload", "-w", str(plist)], check=False)
    subprocess.run(["launchctl", "load", "-w", str(plist)], check=True)
```

- [ ] **Step 5.4: Run macOS tests**

Run: `pytest tests/install/test_user_service_darwin.py -v`
Expected: 3 passed (macOS only).

- [ ] **Step 5.5: Commit**

```bash
git add src/piighost/install/service/_user_service_darwin.py \
        tests/install/test_user_service_darwin.py
git commit -m "feat(install): user-level auto-restart service (macOS LaunchAgent)"
```

---

### Task 6: `_user_service_windows.py` — schtasks /onlogon backend

**Files:**
- Create: `src/piighost/install/service/_user_service_windows.py`
- Test: `tests/install/test_user_service_windows.py`

- [ ] **Step 6.1: Write failing Windows test**

```python
# tests/install/test_user_service_windows.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only", allow_module_level=True)

from unittest.mock import patch

from piighost.install.service.user_service import (
    UserServiceSpec,
    install,
    uninstall,
    status,
)


@pytest.fixture
def spec(tmp_path):
    return UserServiceSpec(
        name="com.piighost.proxy",
        bin_path=Path(r"C:\tools\piighost.exe"),
        vault_dir=tmp_path / "vault",
        log_dir=tmp_path / "logs",
        listen_port=8443,
    )


def test_install_creates_scheduled_task(spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        install(spec)
    args_first = run.call_args_list[0].args[0]
    assert args_first[0].lower().endswith("schtasks.exe")
    assert "/create" in args_first
    assert "/sc" in args_first and "onlogon" in args_first
    assert "/rl" in args_first and "limited" in args_first
    assert any("piighost" in a.lower() for a in args_first)


def test_uninstall_deletes_task(spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        uninstall(spec)
    args_first = run.call_args_list[0].args[0]
    assert "/delete" in args_first
    assert "/f" in args_first


def test_status_reports_running(spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "Status: Running\r\n"
        result = status(spec)
    assert result == "running"


def test_status_reports_missing(spec):
    with patch("subprocess.run") as run:
        run.return_value.returncode = 1
        run.return_value.stdout = ""
        result = status(spec)
    assert result == "missing"
```

- [ ] **Step 6.2: Verify failure**

Run: `pytest tests/install/test_user_service_windows.py -v`
Expected: ImportError.

- [ ] **Step 6.3: Implement**

```python
# src/piighost/install/service/_user_service_windows.py
"""schtasks /onlogon backend (Windows) for piighost proxy auto-restart.

Windows has no native unprivileged equivalent of LaunchAgent's
KeepAlive — the Scheduled Task only fires at logon. If the daemon
crashes mid-session, it will not be restarted until the next logon.
We document this in docs/install-paths.md and recommend running
`piighost serve` from a terminal for long-lived dev sessions, or
using strict mode (with admin) when uptime matters.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from piighost.install.service.user_service import UserServiceSpec


def _task_name(spec: UserServiceSpec) -> str:
    return r"\piighost\proxy"


def _schtasks() -> str:
    return os.path.join(os.environ["SystemRoot"], "System32", "schtasks.exe")


def install(spec: UserServiceSpec) -> None:
    spec.log_dir.mkdir(parents=True, exist_ok=True)
    cmd = (
        f'"{spec.bin_path}" serve --listen-port {spec.listen_port}'
    )
    subprocess.run(
        [
            _schtasks(),
            "/create",
            "/tn", _task_name(spec),
            "/tr", cmd,
            "/sc", "onlogon",
            "/rl", "limited",
            "/f",  # overwrite if exists
        ],
        check=True,
    )


def uninstall(spec: UserServiceSpec) -> None:
    subprocess.run(
        [_schtasks(), "/delete", "/tn", _task_name(spec), "/f"],
        check=False,
    )


def status(spec: UserServiceSpec) -> str:
    proc = subprocess.run(
        [_schtasks(), "/query", "/tn", _task_name(spec), "/v", "/fo", "list"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return "missing"
    if "Running" in proc.stdout:
        return "running"
    return "stopped"


def restart(spec: UserServiceSpec) -> None:
    subprocess.run(
        [_schtasks(), "/end", "/tn", _task_name(spec)], check=False
    )
    subprocess.run(
        [_schtasks(), "/run", "/tn", _task_name(spec)], check=True
    )
```

- [ ] **Step 6.4: Run Windows tests**

Run: `pytest tests/install/test_user_service_windows.py -v`
Expected: 4 passed (Windows only).

- [ ] **Step 6.5: Commit**

```bash
git add src/piighost/install/service/_user_service_windows.py \
        tests/install/test_user_service_windows.py
git commit -m "feat(install): user-level auto-restart service (windows schtasks)"
```

---

### Task 7: `recovery.py` — connect/disconnect implementations

**Files:**
- Create: `src/piighost/install/recovery.py`
- Test: `tests/install/test_recovery.py`

- [ ] **Step 7.1: Write failing test**

```python
# tests/install/test_recovery.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from piighost.install.clients import register
from piighost.install.plan import Client, Embedder, InstallPlan, Mode
from piighost.install.recovery import connect, disconnect


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def _full_plan(home: Path) -> InstallPlan:
    return InstallPlan(
        mode=Mode.FULL,
        vault_dir=home / "vault",
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=frozenset({Client.CLAUDE_CODE}),
        install_user_service=True,
        warmup_models=False,
        force=False,
        dry_run=False,
    )


def test_disconnect_removes_base_url_keeps_mcp(isolated_home):
    register(_full_plan(isolated_home), Client.CLAUDE_CODE)
    disconnect(frozenset({Client.CLAUDE_CODE}))
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})
    assert "piighost" in settings["mcpServers"]


def test_connect_re_adds_base_url(isolated_home):
    register(_full_plan(isolated_home), Client.CLAUDE_CODE)
    disconnect(frozenset({Client.CLAUDE_CODE}))
    connect(frozenset({Client.CLAUDE_CODE}))
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"


def test_disconnect_default_targets_all_existing_clients(isolated_home):
    register(_full_plan(isolated_home), Client.CLAUDE_CODE)
    disconnect(None)  # default = all detected
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_connect_no_op_when_no_config_exists(isolated_home):
    # Should not raise even though no settings file exists
    connect(frozenset({Client.CLAUDE_CODE}))
```

- [ ] **Step 7.2: Verify failure**

Run: `pytest tests/install/test_recovery.py -v`
Expected: ImportError on `recovery`.

- [ ] **Step 7.3: Implement**

```python
# src/piighost/install/recovery.py
"""piighost connect / disconnect — toggle ANTHROPIC_BASE_URL in
client configs without touching the MCP server registration.

Both commands are stateless: they rewrite JSON. They work whether
the proxy daemon is running, stopped, or completely uninstalled.
"""
from __future__ import annotations

import json
from pathlib import Path

from piighost.install.clients import (
    _read_config,
    _write_config,
    detect_all,
    claude_code_settings_path,
)
from piighost.install.plan import Client


_PROXY_BASE_URL = "https://localhost:8443"


def connect(clients: frozenset[Client] | None = None) -> None:
    """Re-add ANTHROPIC_BASE_URL=https://localhost:8443 to the named
    Claude Code config. (Claude Desktop doesn't honour env there.)
    Default: all detected clients."""
    targets = _resolve(clients)
    for client in targets:
        if client is not Client.CLAUDE_CODE:
            continue  # only Claude Code uses the env var
        path = claude_code_settings_path()
        if not path.exists():
            continue
        config = _read_config(path)
        config.setdefault("env", {})["ANTHROPIC_BASE_URL"] = _PROXY_BASE_URL
        _write_config(path, config)


def disconnect(clients: frozenset[Client] | None = None) -> None:
    """Remove ANTHROPIC_BASE_URL from the named clients' configs.
    Default: all detected clients. Leaves MCP server registration intact."""
    targets = _resolve(clients)
    for client in targets:
        if client is not Client.CLAUDE_CODE:
            continue
        path = claude_code_settings_path()
        if not path.exists():
            continue
        config = _read_config(path)
        env = config.get("env") or {}
        env.pop("ANTHROPIC_BASE_URL", None)
        if env:
            config["env"] = env
        else:
            config.pop("env", None)
        _write_config(path, config)


def _resolve(clients: frozenset[Client] | None) -> frozenset[Client]:
    if clients is not None:
        return clients
    return frozenset(loc.client for loc in detect_all() if loc.exists)
```

- [ ] **Step 7.4: Run tests**

Run: `pytest tests/install/test_recovery.py -v`
Expected: 4 passed.

- [ ] **Step 7.5: Commit**

```bash
git add src/piighost/install/recovery.py tests/install/test_recovery.py
git commit -m "feat(install): connect/disconnect — toggle BASE_URL without editing JSON"
```

---

### Task 8: `modes.py` — wrap existing _run_light/strict + add run_mcp_only

**Files:**
- Create: `src/piighost/install/modes.py`
- Test: `tests/install/test_modes.py`

- [ ] **Step 8.1: Write failing test**

```python
# tests/install/test_modes.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from piighost.install.modes import (
    run_light_mode_proxy,
    run_strict_mode_proxy,
    run_mcp_only,
)
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _plan(tmp_path, mode, **overrides):
    base = dict(
        mode=mode,
        vault_dir=tmp_path / "vault",
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=frozenset(),
        install_user_service=mode is not Mode.MCP_ONLY,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    base.update(overrides)
    return InstallPlan(**base)


def test_run_light_mode_proxy_invokes_legacy_runner(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(
        "piighost.install._run_light_mode",
        lambda: called.setdefault("light", True),
    )
    plan = _plan(tmp_path, Mode.FULL)
    run_light_mode_proxy(plan)
    assert called.get("light") is True


def test_run_strict_mode_proxy_invokes_legacy_runner(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(
        "piighost.install._run_strict_mode",
        lambda: called.setdefault("strict", True),
    )
    plan = _plan(tmp_path, Mode.STRICT)
    run_strict_mode_proxy(plan)
    assert called.get("strict") is True


def test_run_mcp_only_is_noop(tmp_path):
    plan = _plan(tmp_path, Mode.MCP_ONLY, install_user_service=False)
    run_mcp_only(plan)  # must not raise
```

- [ ] **Step 8.2: Verify failure**

Run: `pytest tests/install/test_modes.py -v`
Expected: ImportError on `modes`.

- [ ] **Step 8.3: Implement modes.py**

```python
# src/piighost/install/modes.py
"""Thin wrappers around the existing _run_light_mode / _run_strict_mode
runners in install/__init__.py, plus a no-op MCP-only runner.

Kept as a separate module so the executor can import it without
forming an import cycle through __init__.
"""
from __future__ import annotations

from piighost.install.plan import InstallPlan


def run_light_mode_proxy(plan: InstallPlan) -> None:
    """CA + leaf cert at <vault>/proxy/. No system changes."""
    from piighost.install import _run_light_mode
    _run_light_mode()  # signature stays env-driven for now


def run_strict_mode_proxy(plan: InstallPlan) -> None:
    """CA for api.anthropic.com + hosts file + sudo service.
    Reachable only via --mode=strict (deprecated)."""
    from piighost.install import _run_strict_mode
    _run_strict_mode()


def run_mcp_only(plan: InstallPlan) -> None:
    """No-op. RAG/extraction work is provided by the installed extras
    at MCP server startup. This runner exists for symmetry and as a
    natural place to add MCP-only-specific setup steps later."""
    return
```

- [ ] **Step 8.4: Run tests**

Run: `pytest tests/install/test_modes.py -v`
Expected: 3 passed.

- [ ] **Step 8.5: Commit**

```bash
git add src/piighost/install/modes.py tests/install/test_modes.py
git commit -m "feat(install): mode runner module (wraps existing runners)"
```

---

### Task 9: `executor.py` — walks an InstallPlan

**Files:**
- Create: `src/piighost/install/executor.py`
- Test: `tests/install/test_executor.py`

- [ ] **Step 9.1: Write failing test**

```python
# tests/install/test_executor.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from piighost.install.executor import execute
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _plan(tmp_path, mode, clients=frozenset(), **overrides):
    base = dict(
        mode=mode,
        vault_dir=tmp_path / "vault",
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=clients,
        install_user_service=mode is not Mode.MCP_ONLY,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    base.update(overrides)
    return InstallPlan(**base)


@pytest.fixture
def fakes(monkeypatch):
    fakes = {
        "modes": MagicMock(),
        "clients": MagicMock(),
        "user_service": MagicMock(),
        "models": MagicMock(),
    }
    monkeypatch.setattr("piighost.install.executor.modes", fakes["modes"])
    monkeypatch.setattr("piighost.install.executor.clients_mod", fakes["clients"])
    monkeypatch.setattr(
        "piighost.install.executor.user_service", fakes["user_service"]
    )
    monkeypatch.setattr("piighost.install.executor.models", fakes["models"])
    return fakes


def test_full_plan_runs_light_proxy_then_clients_then_user_service(tmp_path, fakes):
    plan = _plan(tmp_path, Mode.FULL, clients=frozenset({Client.CLAUDE_CODE}))
    execute(plan)
    fakes["modes"].run_light_mode_proxy.assert_called_once_with(plan)
    fakes["clients"].register.assert_called_once_with(plan, Client.CLAUDE_CODE)
    fakes["user_service"].install.assert_called_once()
    fakes["models"].warmup.assert_not_called()  # warmup_models=False


def test_mcp_only_skips_proxy_and_user_service(tmp_path, fakes):
    plan = _plan(
        tmp_path,
        Mode.MCP_ONLY,
        clients=frozenset({Client.CLAUDE_CODE}),
        install_user_service=False,
    )
    execute(plan)
    fakes["modes"].run_light_mode_proxy.assert_not_called()
    fakes["modes"].run_strict_mode_proxy.assert_not_called()
    fakes["modes"].run_mcp_only.assert_called_once_with(plan)
    fakes["clients"].register.assert_called_once_with(plan, Client.CLAUDE_CODE)
    fakes["user_service"].install.assert_not_called()


def test_strict_runs_strict_proxy(tmp_path, fakes):
    plan = _plan(
        tmp_path,
        Mode.STRICT,
        clients=frozenset(),
        install_user_service=True,
    )
    execute(plan)
    fakes["modes"].run_strict_mode_proxy.assert_called_once_with(plan)
    fakes["clients"].register.assert_not_called()


def test_dry_run_prints_and_skips_actions(tmp_path, capsys, fakes):
    plan = _plan(
        tmp_path,
        Mode.FULL,
        clients=frozenset({Client.CLAUDE_CODE}),
        dry_run=True,
    )
    execute(plan)
    captured = capsys.readouterr()
    assert "Generate CA" in captured.out or "CA" in captured.out
    fakes["modes"].run_light_mode_proxy.assert_not_called()


def test_warmup_runs_when_requested(tmp_path, fakes):
    plan = _plan(
        tmp_path,
        Mode.FULL,
        clients=frozenset(),
        warmup_models=True,
    )
    execute(plan)
    fakes["models"].warmup.assert_called_once()
```

- [ ] **Step 9.2: Verify failure**

Run: `pytest tests/install/test_executor.py -v`
Expected: ImportError on `executor`.

- [ ] **Step 9.3: Implement**

```python
# src/piighost/install/executor.py
"""Walk an InstallPlan, calling focused helpers for each step.

Importable shape: the modules used as collaborators are bound to
module-level names so tests can monkeypatch them as a single hook.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from piighost.install import clients as clients_mod
from piighost.install import models, modes
from piighost.install.plan import Client, Embedder, InstallPlan, Mode
from piighost.install.service import user_service
from piighost.install.service.user_service import UserServiceSpec
from piighost.install.ui import info, step, success


def execute(plan: InstallPlan) -> None:
    """Execute the plan. Producers (interactive / flags) build the plan;
    this function is the only place that performs side effects."""
    if plan.dry_run:
        print("piighost install — DRY RUN. Would do:")
        print(plan.describe())
        return

    _ensure_dirs(plan)

    if plan.mode is Mode.FULL:
        step("Setting up anonymizing proxy (light mode)")
        modes.run_light_mode_proxy(plan)
    elif plan.mode is Mode.STRICT:
        step("Setting up anonymizing proxy (strict mode)")
        modes.run_strict_mode_proxy(plan)
    else:
        modes.run_mcp_only(plan)

    for client in sorted(plan.clients):
        step(f"Registering MCP server in {_client_label(client)}")
        clients_mod.register(plan, client)

    if plan.install_user_service and plan.mode is not Mode.MCP_ONLY:
        step("Installing user-level auto-restart service")
        user_service.install(_spec_for(plan))

    if plan.warmup_models:
        step("Downloading model weights")
        models.warmup(_load_service_config(plan), dry_run=False)

    _print_next_steps(plan)


def _ensure_dirs(plan: InstallPlan) -> None:
    plan.vault_dir.mkdir(parents=True, exist_ok=True)
    home = Path("~").expanduser()
    (home / ".piighost" / "proxy").mkdir(parents=True, exist_ok=True)
    (home / ".piighost" / "logs").mkdir(parents=True, exist_ok=True)


def _spec_for(plan: InstallPlan) -> UserServiceSpec:
    bin_path = Path(shutil.which("piighost") or "piighost")
    log_dir = Path("~").expanduser() / ".piighost" / "logs"
    return UserServiceSpec(
        name="com.piighost.proxy",
        bin_path=bin_path,
        vault_dir=plan.vault_dir,
        log_dir=log_dir,
        listen_port=8443,
    )


def _load_service_config(plan: InstallPlan):
    from piighost.service.config import ServiceConfig
    cfg = ServiceConfig.default()
    if plan.embedder is Embedder.MISTRAL:
        cfg.embedder.backend = "mistral"
    elif plan.embedder is Embedder.NONE:
        cfg.embedder.backend = "none"
    return cfg


def _client_label(c: Client) -> str:
    return {Client.CLAUDE_CODE: "Claude Code", Client.CLAUDE_DESKTOP: "Claude Desktop"}[c]


def _print_next_steps(plan: InstallPlan) -> None:
    success("\npiighost installed.\n")
    info("Useful commands:")
    info("  piighost status          - is the proxy running?")
    info("  piighost on / off        - toggle anonymization")
    info("  piighost connect / disconnect")
    info("                           - add/remove ANTHROPIC_BASE_URL")
    info("  piighost doctor          - diagnose & self-heal")
    info("  piighost uninstall       - clean removal\n")
    info("Last-resort recovery (if 'piighost' itself is broken):")
    info("  Edit ~/.claude/settings.json and remove env.ANTHROPIC_BASE_URL.")
```

- [ ] **Step 9.4: Run tests**

Run: `pytest tests/install/test_executor.py -v`
Expected: 5 passed.

- [ ] **Step 9.5: Commit**

```bash
git add src/piighost/install/executor.py tests/install/test_executor.py
git commit -m "feat(install): executor walks the plan + delegates to focused helpers"
```

---

### Task 10: `interactive.py` — rich-driven prompts

**Files:**
- Create: `src/piighost/install/interactive.py`
- Test: `tests/install/test_interactive.py`

- [ ] **Step 10.1: Write failing test**

```python
# tests/install/test_interactive.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from piighost.install.interactive import build_plan_interactively
from piighost.install.plan import Client, Embedder, Mode


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def _scripted(answers: list[str]):
    """Make a fake `Console.input`-like callable that returns answers in order."""
    it = iter(answers)

    def _ask(prompt, **kw):
        return next(it)

    return _ask


def test_default_full_flow(isolated_home, monkeypatch):
    # mode=full, both clients (auto-detect would find none — user picks both),
    # default vault dir, embedder=local
    answers = ["1", "1,2", "", "1", "y"]
    monkeypatch.setattr(
        "piighost.install.interactive._ask", _scripted(answers)
    )
    plan = build_plan_interactively(starting_defaults=None)
    assert plan.mode is Mode.FULL
    assert plan.clients == frozenset({Client.CLAUDE_CODE, Client.CLAUDE_DESKTOP})
    assert plan.embedder is Embedder.LOCAL


def test_mcp_only_no_clients(isolated_home, monkeypatch):
    answers = ["2", "", "", "1", "y"]  # mcp-only, no clients, default vault, local
    monkeypatch.setattr(
        "piighost.install.interactive._ask", _scripted(answers)
    )
    plan = build_plan_interactively(starting_defaults=None)
    assert plan.mode is Mode.MCP_ONLY
    assert plan.clients == frozenset()
    assert plan.install_user_service is False


def test_mistral_prompts_for_key(isolated_home, monkeypatch):
    answers = ["1", "1", "", "2", "sk-test", "y"]
    monkeypatch.setattr(
        "piighost.install.interactive._ask", _scripted(answers)
    )
    plan = build_plan_interactively(starting_defaults=None)
    assert plan.embedder is Embedder.MISTRAL
    assert plan.mistral_api_key == "sk-test"


def test_user_aborts_at_review(isolated_home, monkeypatch):
    answers = ["1", "1", "", "1", "n"]
    monkeypatch.setattr(
        "piighost.install.interactive._ask", _scripted(answers)
    )
    with pytest.raises(SystemExit):
        build_plan_interactively(starting_defaults=None)
```

- [ ] **Step 10.2: Verify failure**

Run: `pytest tests/install/test_interactive.py -v`
Expected: ImportError on `interactive`.

- [ ] **Step 10.3: Implement**

```python
# src/piighost/install/interactive.py
"""Interactive prompts for `piighost install` when stdin is a TTY.

Uses a single `_ask` indirection so tests can swap the input source
for a scripted iterator.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from piighost.install.clients import detect_all
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _ask(prompt: str, *, default: str = "") -> str:
    """Default input source. Tests monkeypatch this."""
    full = f"{prompt} " + (f"[{default}] " if default else "")
    raw = input(full).strip()
    return raw or default


def build_plan_interactively(starting_defaults: InstallPlan | None) -> InstallPlan:
    """Walk the user through 4 prompts + final review. Raise SystemExit
    if the user declines at the review."""
    print()
    print("┌─ piighost install ───────────────────────────────────────")
    print("│")
    mode = _prompt_mode()
    clients = _prompt_clients()
    vault_dir = _prompt_vault_dir()
    embedder, mistral_key = _prompt_embedder()

    install_user_service = mode is not Mode.MCP_ONLY

    plan = InstallPlan(
        mode=mode,
        vault_dir=vault_dir,
        embedder=embedder,
        mistral_api_key=mistral_key,
        clients=clients,
        install_user_service=install_user_service,
        warmup_models=False,
        force=False,
        dry_run=False,
    )

    print()
    print("Review:")
    print(plan.describe())
    print()
    answer = _ask("Proceed? [Y/n]", default="y").lower()
    if answer not in ("y", "yes"):
        print("Aborted.")
        raise SystemExit(1)

    return plan


def _prompt_mode() -> Mode:
    print("│ 1. Mode")
    print("│    1) Full      Anonymizing proxy + MCP tools + RAG")
    print("│    2) MCP-only  MCP tools + RAG. No proxy.")
    raw = _ask("│  Choose:", default="1")
    if raw in ("1", "full"):
        return Mode.FULL
    if raw in ("2", "mcp-only"):
        return Mode.MCP_ONLY
    print(f"│  Unknown choice {raw!r}, defaulting to Full.")
    return Mode.FULL


def _prompt_clients() -> frozenset[Client]:
    detected = {loc.client: loc.exists for loc in detect_all()}
    print("│")
    print("│ 2. Register MCP server in (csv: 1=Code, 2=Desktop, blank=none):")
    for i, client in enumerate([Client.CLAUDE_CODE, Client.CLAUDE_DESKTOP], start=1):
        marker = "✓" if detected.get(client) else " "
        print(f"│    {i}) [{marker}] {_label(client)}")
    raw = _ask("│  Choose:", default=_default_client_csv(detected))
    if not raw.strip():
        return frozenset()
    out: set[Client] = set()
    mapping = {"1": Client.CLAUDE_CODE, "2": Client.CLAUDE_DESKTOP}
    for tok in raw.split(","):
        tok = tok.strip()
        if tok in mapping:
            out.add(mapping[tok])
    return frozenset(out)


def _prompt_vault_dir() -> Path:
    default = Path.home() / ".piighost" / "vault"
    print("│")
    raw = _ask("│ 3. Vault directory", default=str(default))
    return Path(raw).expanduser()


def _prompt_embedder() -> tuple[Embedder, str | None]:
    print("│")
    print("│ 4. Embedder backend")
    print("│    1) Local    ~500 MB download, runs offline")
    print("│    2) Mistral  Remote API, needs MISTRAL_API_KEY")
    print("│    3) None     Skip RAG embedding (anonymize-only)")
    raw = _ask("│  Choose:", default="1")
    if raw in ("2", "mistral"):
        key = (
            os.environ.get("MISTRAL_API_KEY")
            or _ask("│  MISTRAL_API_KEY:", default="")
            or None
        )
        if not key:
            print("│  No API key supplied; falling back to local embedder.")
            return Embedder.LOCAL, None
        return Embedder.MISTRAL, key
    if raw in ("3", "none"):
        return Embedder.NONE, None
    return Embedder.LOCAL, None


def _default_client_csv(detected: dict[Client, bool]) -> str:
    csv: list[str] = []
    if detected.get(Client.CLAUDE_CODE):
        csv.append("1")
    if detected.get(Client.CLAUDE_DESKTOP):
        csv.append("2")
    return ",".join(csv)


def _label(c: Client) -> str:
    return {Client.CLAUDE_CODE: "Claude Code", Client.CLAUDE_DESKTOP: "Claude Desktop"}[c]
```

- [ ] **Step 10.4: Run tests**

Run: `pytest tests/install/test_interactive.py -v`
Expected: 4 passed.

- [ ] **Step 10.5: Commit**

```bash
git add src/piighost/install/interactive.py tests/install/test_interactive.py
git commit -m "feat(install): interactive 4-prompt flow producing an InstallPlan"
```

---

### Task 11: Wire `piighost connect` / `piighost disconnect` into the CLI

**Files:**
- Create: `src/piighost/cli/commands/connect.py`
- Create: `src/piighost/cli/commands/disconnect.py`
- Modify: `src/piighost/cli/main.py`
- Test: `tests/install/test_recovery_cli.py`

- [ ] **Step 11.1: Write failing CLI test**

```python
# tests/install/test_recovery_cli.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app
from piighost.install.clients import register
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


runner = CliRunner()


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def _seed_full_install(home: Path) -> None:
    plan = InstallPlan(
        mode=Mode.FULL,
        vault_dir=home / "vault",
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=frozenset({Client.CLAUDE_CODE}),
        install_user_service=True,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    register(plan, Client.CLAUDE_CODE)


def test_disconnect_command_removes_base_url(isolated_home):
    _seed_full_install(isolated_home)
    result = runner.invoke(app, ["disconnect"])
    assert result.exit_code == 0
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_connect_command_re_adds_base_url(isolated_home):
    _seed_full_install(isolated_home)
    runner.invoke(app, ["disconnect"])
    result = runner.invoke(app, ["connect"])
    assert result.exit_code == 0
    settings = json.loads((isolated_home / ".claude" / "settings.json").read_text())
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"
```

- [ ] **Step 11.2: Verify failure**

Run: `pytest tests/install/test_recovery_cli.py -v`
Expected: missing typer commands.

- [ ] **Step 11.3: Implement command modules**

```python
# src/piighost/cli/commands/connect.py
"""piighost connect — restore ANTHROPIC_BASE_URL in client config(s)."""
from __future__ import annotations

from typing import Annotated, Optional

import typer

from piighost.install.plan import Client
from piighost.install.recovery import connect


def run(
    client: Annotated[
        Optional[str],
        typer.Option(
            "--client",
            help="Comma-separated client list (code, desktop). Default: all detected.",
        ),
    ] = None,
) -> None:
    """Add ANTHROPIC_BASE_URL=https://localhost:8443 to your Claude
    client(s) so traffic is routed through the local anonymizing proxy.
    Reverses `piighost disconnect`."""
    targets = _parse(client)
    connect(targets)
    typer.echo("Connected. Anthropic API calls now route through the local proxy.")


def _parse(raw: str | None) -> frozenset[Client] | None:
    if raw is None:
        return None
    out: set[Client] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if tok == "code":
            out.add(Client.CLAUDE_CODE)
        elif tok == "desktop":
            out.add(Client.CLAUDE_DESKTOP)
        else:
            raise typer.BadParameter(
                f"unknown client {tok!r}. Valid: code, desktop."
            )
    return frozenset(out)
```

```python
# src/piighost/cli/commands/disconnect.py
"""piighost disconnect — remove ANTHROPIC_BASE_URL from client config(s)."""
from __future__ import annotations

from typing import Annotated, Optional

import typer

from piighost.install.plan import Client
from piighost.install.recovery import disconnect


def run(
    client: Annotated[
        Optional[str],
        typer.Option(
            "--client",
            help="Comma-separated client list (code, desktop). Default: all detected.",
        ),
    ] = None,
) -> None:
    """Remove ANTHROPIC_BASE_URL from your Claude client config(s).
    The MCP server registration is preserved — disconnecting only stops
    proxy interception, leaves your tools available."""
    targets = _parse(client)
    disconnect(targets)
    typer.echo("Disconnected. Anthropic API calls go directly to api.anthropic.com.")


def _parse(raw: str | None) -> frozenset[Client] | None:
    if raw is None:
        return None
    out: set[Client] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if tok == "code":
            out.add(Client.CLAUDE_CODE)
        elif tok == "desktop":
            out.add(Client.CLAUDE_DESKTOP)
        else:
            raise typer.BadParameter(
                f"unknown client {tok!r}. Valid: code, desktop."
            )
    return frozenset(out)
```

- [ ] **Step 11.4: Wire into `cli/main.py`**

In `src/piighost/cli/main.py`, after the existing imports add:

```python
from piighost.cli.commands import connect as connect_cmd
from piighost.cli.commands import disconnect as disconnect_cmd
```

After the existing `app.command(...)` registrations (near the existing `state_cmd` block) add:

```python
app.command("connect", help="Add ANTHROPIC_BASE_URL to your Claude client(s).")(connect_cmd.run)
app.command("disconnect", help="Remove ANTHROPIC_BASE_URL from your Claude client(s).")(disconnect_cmd.run)
```

- [ ] **Step 11.5: Run CLI test**

Run: `pytest tests/install/test_recovery_cli.py -v`
Expected: 2 passed.

- [ ] **Step 11.6: Commit**

```bash
git add src/piighost/cli/commands/connect.py \
        src/piighost/cli/commands/disconnect.py \
        src/piighost/cli/main.py \
        tests/install/test_recovery_cli.py
git commit -m "feat(cli): connect/disconnect commands"
```

---

### Task 12: Rewrite `install/__init__.py` to use the new architecture

**Files:**
- Modify: `src/piighost/install/__init__.py` (significant)
- Modify: `tests/unit/install/test_install_cmd.py`
- Test: `tests/install/test_install_e2e.py` (new)

- [ ] **Step 12.1: Write failing e2e test**

```python
# tests/install/test_install_e2e.py
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app


runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_install_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("PIIGHOST_SKIP_TRUSTSTORE", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_SERVICE", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_USERSVC", "1")
    import piighost.install.trust_store as ts
    monkeypatch.setattr(ts, "install_ca", lambda _p: None)
    return tmp_path


def test_install_full_with_yes_writes_settings(isolated_install_env):
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=full",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = json.loads(
        (isolated_install_env / ".claude" / "settings.json").read_text()
    )
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"
    assert "piighost" in settings["mcpServers"]


def test_install_mcp_only_no_base_url(isolated_install_env):
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=mcp-only",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = json.loads(
        (isolated_install_env / ".claude" / "settings.json").read_text()
    )
    assert "piighost" in settings["mcpServers"]
    assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})


def test_install_dry_run_does_nothing(isolated_install_env):
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=full",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--dry-run",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert not (isolated_install_env / ".claude" / "settings.json").exists()


def test_install_light_alias_emits_deprecation(isolated_install_env):
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=light",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert "[deprecated]" in result.output
    assert "--mode=light" in result.output


def test_install_strict_emits_advanced_warning(isolated_install_env):
    # Strict still proceeds, but with the [advanced] warning, and the
    # user_service/trust_store side-effects are skipped via env vars.
    result = runner.invoke(
        app,
        [
            "install",
            "--mode=strict",
            f"--vault-dir={isolated_install_env / 'vault'}",
            "--clients=code",
            "--embedder=local",
            "--yes",
        ],
    )
    assert "[advanced]" in result.output
```

- [ ] **Step 12.2: Verify failure**

Run: `pytest tests/install/test_install_e2e.py -v`
Expected: failures (the new flag set isn't wired yet).

- [ ] **Step 12.3: Rewrite `install/__init__.py`**

```python
# src/piighost/install/__init__.py
"""piighost install — typer entry point.

The interactive flow lives in `interactive.py`. The flag parser
lives in `flags.py`. Both produce an InstallPlan, which the
`executor` then walks.

`_run_light_mode` and `_run_strict_mode` are preserved as private
helpers called from `modes.py` so the existing logic for CA / leaf
cert / hosts file / service registration doesn't have to be moved.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from piighost.install import ca as ca_mod
from piighost.install import trust_store
from piighost.install.executor import execute
from piighost.install.flags import parse_flags
from piighost.install.interactive import build_plan_interactively
from piighost.install.ui import error, info, step, success, warn


def run(
    mode: Annotated[Optional[str], typer.Option(
        "--mode", help="full | mcp-only | strict (advanced) | light (deprecated)"
    )] = None,
    vault_dir: Annotated[Optional[Path], typer.Option(
        "--vault-dir", help="Where to store the PII vault and indexed docs."
    )] = None,
    embedder: Annotated[Optional[str], typer.Option(
        "--embedder", help="local | mistral | none"
    )] = None,
    mistral_api_key: Annotated[Optional[str], typer.Option(
        "--mistral-api-key", help="Required when --embedder=mistral."
    )] = None,
    clients: Annotated[Optional[str], typer.Option(
        "--clients", help="Comma-separated: code, desktop. Default: auto-detect."
    )] = None,
    user_service: Annotated[Optional[bool], typer.Option(
        "--user-service/--no-user-service",
        help="Install user-level auto-restart service (default: yes for full/strict, no for mcp-only).",
    )] = None,
    warmup: Annotated[bool, typer.Option(
        "--warmup", help="Download model weights now instead of lazy on first use."
    )] = False,
    force: Annotated[bool, typer.Option(
        "--force", help="Overwrite conflicting MCP entries / config."
    )] = False,
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", help="Print what would happen, don't change anything."
    )] = False,
    yes: Annotated[bool, typer.Option(
        "--yes", "-y", help="Skip the final confirmation prompt."
    )] = False,
) -> None:
    """Install piighost with the chosen mode and integrations."""
    plan = _produce_plan(
        mode, vault_dir, embedder, mistral_api_key,
        clients, user_service, warmup, force, dry_run, yes,
    )
    execute(plan)


def _produce_plan(
    mode, vault_dir, embedder, mistral_api_key,
    clients, user_service, warmup, force, dry_run, yes,
):
    explicit_flags = any(
        v is not None for v in (mode, vault_dir, embedder, mistral_api_key, clients, user_service)
    )
    if _should_prompt(yes, dry_run, explicit_flags):
        plan = build_plan_interactively(starting_defaults=None)
        return plan

    try:
        result = parse_flags(
            mode=mode,
            vault_dir=vault_dir,
            embedder=embedder,
            mistral_api_key=mistral_api_key,
            clients=clients,
            user_service=user_service,
            warmup=warmup,
            force=force,
            dry_run=dry_run,
            yes=yes,
            env=dict(os.environ),
        )
    except ValueError as exc:
        error(str(exc))
        raise typer.Exit(code=1)

    for d in result.deprecations:
        warn(d.message)
    return result.plan


def _should_prompt(yes: bool, dry_run: bool, explicit_flags: bool) -> bool:
    if yes or dry_run or explicit_flags:
        return False
    return sys.stdin.isatty()


# ---- legacy private helpers preserved for modes.py ----------------------

def _run_light_mode() -> None:
    """Phase 1 light-mode orchestration: CA generation. Client wiring
    moved to clients.py — this no longer writes settings.json directly."""
    step("Generating local root CA and leaf certificate")
    vault = Path(os.path.expanduser("~")) / ".piighost"
    proxy_dir = vault / "proxy"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    root = ca_mod.generate_root(common_name="piighost local CA")
    leaf = ca_mod.generate_leaf(root, hostnames=["localhost", "127.0.0.1"])
    (proxy_dir / "ca.pem").write_bytes(root.cert_pem)
    (proxy_dir / "ca.key").write_bytes(root.key_pem)
    (proxy_dir / "leaf.pem").write_bytes(leaf.cert_pem)
    (proxy_dir / "leaf.key").write_bytes(leaf.key_pem)
    success("CA and leaf cert written to ~/.piighost/proxy/")

    step("Installing CA into OS trust store")
    if os.environ.get("PIIGHOST_SKIP_TRUSTSTORE") == "1":
        info("PIIGHOST_SKIP_TRUSTSTORE=1 — skipping trust store installation.")
    else:
        try:
            trust_store.install_ca(proxy_dir / "ca.pem")
            success("CA installed in OS trust store.")
        except Exception as exc:
            warn(f"Trust store install failed: {exc} — install manually.")


def _run_strict_mode() -> None:
    """Phase 2 strict-mode: CA for api.anthropic.com + hosts file +
    sudo background service on :443. Reachable only via --mode=strict."""
    import shutil
    vault = Path(os.path.expanduser("~")) / ".piighost"
    proxy_dir = vault / "proxy"
    proxy_dir.mkdir(parents=True, exist_ok=True)

    step("Generating local root CA and leaf certificate for api.anthropic.com")
    root = ca_mod.generate_root(common_name="piighost local CA")
    leaf = ca_mod.generate_leaf(root, hostnames=["api.anthropic.com"])
    (proxy_dir / "ca.pem").write_bytes(root.cert_pem)
    (proxy_dir / "ca.key").write_bytes(root.key_pem)
    (proxy_dir / "leaf.pem").write_bytes(leaf.cert_pem)
    (proxy_dir / "leaf.key").write_bytes(leaf.key_pem)
    success("CA and leaf cert written to ~/.piighost/proxy/")

    step("Installing CA into OS trust store")
    if os.environ.get("PIIGHOST_SKIP_TRUSTSTORE") == "1":
        info("PIIGHOST_SKIP_TRUSTSTORE=1 — skipping trust store installation.")
    else:
        try:
            trust_store.install_ca(proxy_dir / "ca.pem")
            success("CA installed in OS trust store.")
        except Exception as exc:
            warn(f"Trust store install failed: {exc} — install manually.")

    step("Editing hosts file (127.0.0.1 api.anthropic.com)")
    from piighost.install import hosts_file as hf
    try:
        hf.add_redirect("api.anthropic.com")
        success("Hosts file updated.")
    except Exception as exc:
        warn(f"Hosts file edit failed: {exc}")

    step("Installing background service (port 443)")
    if os.environ.get("PIIGHOST_SKIP_SERVICE") == "1":
        info("PIIGHOST_SKIP_SERVICE=1 — skipping service installation.")
    else:
        from piighost.install import service as svc
        bin_path = shutil.which("piighost")
        if bin_path is None:
            warn(
                "piighost binary not found on PATH. "
                "Service registration requires piighost to be installed as a command. "
                "Run: pip install piighost[proxy]"
            )
            warn("Skipping service installation.")
        else:
            spec = svc.ServiceSpec(
                name="com.piighost.proxy",
                bin_path=bin_path,
                vault_dir=vault,
                cert_path=proxy_dir / "leaf.pem",
                key_path=proxy_dir / "leaf.key",
                port=443,
            )
            try:
                svc.install_service(spec)
                success("Background service installed and started.")
            except Exception as exc:
                warn(f"Service install failed: {exc}")
```

- [ ] **Step 12.4: Update `executor.py` to honour `PIIGHOST_SKIP_USERSVC`**

In `src/piighost/install/executor.py`, change the user-service branch:

```python
    if plan.install_user_service and plan.mode is not Mode.MCP_ONLY:
        if os.environ.get("PIIGHOST_SKIP_USERSVC") == "1":
            info("PIIGHOST_SKIP_USERSVC=1 — skipping user-service installation.")
        else:
            step("Installing user-level auto-restart service")
            user_service.install(_spec_for(plan))
```

(Add `import os` near the top of the file.)

- [ ] **Step 12.5: Update `tests/unit/install/test_install_cmd.py`**

Replace the existing test bodies with these (the autouse `_isolated_install_env` fixture from earlier in this session stays):

```python
def test_install_dry_run_exits_zero():
    result = runner.invoke(
        app, ["install", "--mode=full", "--clients=code", "--dry-run", "--yes"]
    )
    assert result.exit_code == 0


def test_install_no_user_service_in_mcp_only():
    result = runner.invoke(
        app, ["install", "--mode=mcp-only", "--clients=code",
              "--no-user-service", "--yes"]
    )
    assert result.exit_code == 0


def test_install_fails_gracefully_on_invalid_mode():
    result = runner.invoke(
        app, ["install", "--mode=galaxybrain", "--yes"]
    )
    assert result.exit_code != 0
    assert "unknown mode" in result.output


def test_install_light_emits_deprecation():
    result = runner.invoke(
        app, ["install", "--mode=light", "--clients=code", "--yes"]
    )
    assert "[deprecated]" in result.output
```

The pre-existing `_all_mocked()` helper and the obsolete `test_install_no_docker_forces_uv_path`/`test_install_fails_gracefully_on_preflight_error` tests are deleted — they tested the legacy preflight branch that no longer exists.

- [ ] **Step 12.6: Run e2e + the rewritten install_cmd tests**

Run: `pytest tests/install/test_install_e2e.py tests/unit/install/test_install_cmd.py -v`
Expected: all passed (5 e2e + 4 install_cmd = 9).

- [ ] **Step 12.7: Run the full install test suite to catch regressions**

Run: `pytest tests/install tests/unit/install -v`
Expected: all green.

- [ ] **Step 12.8: Commit**

```bash
git add src/piighost/install/__init__.py src/piighost/install/executor.py \
        tests/install/test_install_e2e.py tests/unit/install/test_install_cmd.py
git commit -m "feat(install): rewrite typer entry point — interactive + flags + executor"
```

---

### Task 13: Extend `doctor` with proxy reachability check

**Files:**
- Modify: `src/piighost/cli/commands/doctor.py`
- Test: `tests/install/test_doctor_reachability.py`

- [ ] **Step 13.1: Write failing test**

```python
# tests/install/test_doctor_reachability.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app


runner = CliRunner()


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def _seed_base_url(home: Path) -> None:
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({
        "env": {"ANTHROPIC_BASE_URL": "https://localhost:8443"}
    }))


def test_doctor_warns_when_base_url_set_but_proxy_unreachable(isolated_home):
    _seed_base_url(isolated_home)
    with patch(
        "piighost.cli.commands.doctor._proxy_reachable", return_value=False
    ):
        result = runner.invoke(app, ["doctor"])
    assert "[FAIL]" in result.output
    assert "8443" in result.output
    assert "piighost disconnect" in result.output


def test_doctor_silent_when_no_base_url_set(isolated_home):
    # No settings.json present — doctor should not complain about the proxy
    with patch(
        "piighost.cli.commands.doctor._proxy_reachable", return_value=False
    ):
        result = runner.invoke(app, ["doctor"])
    assert "8443" not in result.output
```

- [ ] **Step 13.2: Verify failure**

Run: `pytest tests/install/test_doctor_reachability.py -v`
Expected: failures (the new check isn't there yet).

- [ ] **Step 13.3: Edit `doctor.py`**

In `src/piighost/cli/commands/doctor.py`, add this check function and call it from the existing `run()`:

```python
import json
import socket
from pathlib import Path

from piighost.install.clients import claude_code_settings_path


def _proxy_reachable(host: str = "localhost", port: int = 8443, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_proxy_reachability() -> tuple[bool, str | None]:
    """Returns (ok, message). ok=True if no problem detected.
    The check only runs if the user has BASE_URL configured."""
    settings_path = claude_code_settings_path()
    if not settings_path.exists():
        return True, None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True, None
    base_url = (data.get("env") or {}).get("ANTHROPIC_BASE_URL")
    if not base_url:
        return True, None
    if "localhost:8443" not in base_url and "127.0.0.1:8443" not in base_url:
        return True, None
    if _proxy_reachable():
        return True, None
    return False, (
        "[FAIL] proxy listening on https://localhost:8443\n"
        "       ANTHROPIC_BASE_URL is set in ~/.claude/settings.json,\n"
        "       but :8443 is unreachable. Anthropic API calls from\n"
        "       Claude Code will fail until the proxy is restarted\n"
        "       OR the BASE_URL is removed.\n\n"
        "       Fix options:\n"
        "         1. Start the proxy:    piighost serve &\n"
        "         2. Disconnect:         piighost disconnect\n"
        "         3. Reinstall service:  piighost install --user-service"
    )
```

In the existing `run()` function, after the existing checks, add:

```python
    ok, msg = _check_proxy_reachability()
    if msg:
        typer.echo(msg)
        if not ok:
            raise typer.Exit(code=2)
```

- [ ] **Step 13.4: Run reachability test**

Run: `pytest tests/install/test_doctor_reachability.py -v`
Expected: 2 passed.

- [ ] **Step 13.5: Run all doctor tests** (in case existing tests broke)

Run: `pytest -k doctor -v`
Expected: all green.

- [ ] **Step 13.6: Commit**

```bash
git add src/piighost/cli/commands/doctor.py tests/install/test_doctor_reachability.py
git commit -m "feat(doctor): warn when BASE_URL is set but proxy is unreachable"
```

---

### Task 14: Update `scripts/install.{sh,ps1}` defaults

**Files:**
- Modify: `scripts/install.sh`
- Modify: `scripts/install.ps1`

- [ ] **Step 14.1: Edit `scripts/install.sh`**

```bash
# At the top, change defaults:
MODE="${PIIGHOST_MODE:-full}"
EXTRAS="${PIIGHOST_EXTRAS:-proxy,gliner2,mcp,index,cache}"
SOURCE="${PIIGHOST_SOURCE:-git+https://github.com/jamon8888/hacienda-ghost.git}"

# Change the banner copy from "piighost installer / mode / extras / source"
# to add a hint about modes:
echo ""
echo "piighost installer"
echo "  mode   : $MODE"
echo "    full       Anonymizing proxy + MCP tools + RAG (default)"
echo "    mcp-only   MCP tools + RAG only, no proxy"
echo "    strict     System-wide proxy (advanced, requires admin)"
echo "  extras : $EXTRAS"
echo "  source : $SOURCE"
echo ""
```

The rest of the script (uv install, stop service, install piighost, run `piighost install --mode=$MODE`) stays as-is.

- [ ] **Step 14.2: Edit `scripts/install.ps1`** with the same changes (PowerShell syntax).

- [ ] **Step 14.3: Smoke check that the scripts pass shellcheck / parse**

Run: `bash -n scripts/install.sh`
Expected: exit 0.

Run: `pwsh -NoProfile -Command "Invoke-Expression (Get-Content -Raw scripts/install.ps1)" -WhatIf`
Expected: parse succeeds.

(If pwsh not available, skip — the `bash -n` check is the gate.)

- [ ] **Step 14.4: Commit**

```bash
git add scripts/install.sh scripts/install.ps1
git commit -m "chore(scripts): default install mode is now 'full' (was 'strict')"
```

---

### Task 15: MCPB sanity — verify build still works + add consistency check

**Files:**
- Create: `scripts/check_mcpb_consistency.py`
- Test: `tests/install/test_mcpb_consistency.py`

- [ ] **Step 15.1: Verify the existing build still works**

Run: `python scripts/build_mcpb.py`
Expected: exit 0; `dist/mcpb/piighost-core.mcpb` and `dist/mcpb/piighost-full.mcpb` exist.

- [ ] **Step 15.2: Write failing consistency test**

```python
# tests/install/test_mcpb_consistency.py
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _root_version() -> str:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    return data["project"]["version"]


@pytest.mark.parametrize("variant", ["core", "full"])
def test_bundle_manifest_version_matches_pyproject(variant):
    bundle = ROOT / "dist" / "mcpb" / f"piighost-{variant}.mcpb"
    if not bundle.exists():
        pytest.skip(f"{bundle} not built; run scripts/build_mcpb.py first")
    with zipfile.ZipFile(bundle) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["version"] == _root_version()


@pytest.mark.parametrize("variant,extras", [("core", "mcp"), ("full", "mcp,index,gliner2")])
def test_bundle_pyproject_pins_correct_extras(variant, extras):
    bundle = ROOT / "dist" / "mcpb" / f"piighost-{variant}.mcpb"
    if not bundle.exists():
        pytest.skip(f"{bundle} not built; run scripts/build_mcpb.py first")
    with zipfile.ZipFile(bundle) as zf:
        body = zf.read("pyproject.toml").decode("utf-8")
    assert f"piighost[{extras}]=={_root_version()}" in body
```

- [ ] **Step 15.3: Build and run**

Run: `python scripts/build_mcpb.py && pytest tests/install/test_mcpb_consistency.py -v`
Expected: 4 passed.

- [ ] **Step 15.4: Add the standalone CI helper**

```python
# scripts/check_mcpb_consistency.py
"""CI helper: assert dist/mcpb/*.mcpb match pyproject.toml version.

Run after every version bump; fails non-zero if a bundle is stale."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    failures: list[str] = []
    for variant in ("core", "full"):
        bundle = ROOT / "dist" / "mcpb" / f"piighost-{variant}.mcpb"
        if not bundle.exists():
            failures.append(f"missing: {bundle}")
            continue
        with zipfile.ZipFile(bundle) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("version") != version:
            failures.append(
                f"{bundle.name}: manifest version "
                f"{manifest.get('version')!r} != pyproject {version!r}"
            )
    if failures:
        print("MCPB consistency check failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"MCPB consistency OK ({version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 15.5: Smoke-run the helper**

Run: `python scripts/check_mcpb_consistency.py`
Expected: `MCPB consistency OK (<version>)`, exit 0.

- [ ] **Step 15.6: Commit**

```bash
git add scripts/check_mcpb_consistency.py tests/install/test_mcpb_consistency.py
git commit -m "chore(mcpb): version-consistency CI check"
```

---

### Task 16: User-facing comparison doc

**Files:**
- Create: `docs/install-paths.md`

- [ ] **Step 16.1: Write the doc**

```markdown
# Install paths: install script vs MCPB bundle

piighost ships two parallel installation channels. They produce
overlapping but not identical end states.

## Quick comparison

|                          | Install script (`curl \| bash`) | MCPB bundle (drag-drop) |
|--------------------------|---------------------------------|-------------------------|
| Audience                 | terminal users                  | GUI-only users          |
| Bootstrap                | `curl ... \| bash`              | drag `.mcpb` onto Claude Desktop |
| Anonymizing proxy        | included in `--mode=full`       | not available           |
| Auto-restart on login    | yes (LaunchAgent / systemd `--user` / schtasks `/onlogon`) | N/A — Claude Desktop manages the extension |
| Vault dir                | user-chosen (default `~/.piighost/vault`) | configured at first install (`${user_config.vault_dir}`) |
| MCP server               | registered in your chosen client(s) | isolated to Desktop's extension sandbox |
| Removal                  | `piighost uninstall`            | Claude Desktop → Settings → Extensions → Remove |

## When to pick which

- **You use Claude Code (terminal CLI agent)** → install script. Only path that registers piighost in `~/.claude/settings.json`.
- **You only use Claude Desktop and don't want a terminal** → MCPB bundle (`piighost-full.mcpb` for RAG, `piighost-core.mcpb` for anonymize-only).
- **You want anonymizing proxy interception of `api.anthropic.com`** → install script with `--mode=full`. Not available via MCPB.
- **You use both Claude Code and Claude Desktop** → install script registers MCP in both.

## Recovery

The install script's `--mode=full` sets `ANTHROPIC_BASE_URL=https://localhost:8443` in Claude Code's settings. If the local proxy stops:

- `piighost connect` / `piighost disconnect` toggle the env var without editing JSON.
- `piighost doctor` detects the case and prints fix options.
- Last-resort: edit `~/.claude/settings.json` and remove `env.ANTHROPIC_BASE_URL`.

The MCPB path doesn't set `ANTHROPIC_BASE_URL` — it can't, because Claude Desktop ignores env vars in extension config. Removing the bundle is the only "off switch" for the MCPB path.

## Coexistence

Both channels can be installed at the same time. They produce two independent MCP server registrations (script-installed appears as `piighost`, MCPB appears as `piighost-full` or `piighost-core` depending on which bundle). Claude Desktop will run whichever is enabled in the Extensions panel.
```

- [ ] **Step 16.2: Commit**

```bash
git add docs/install-paths.md
git commit -m "docs: install-paths.md — script vs MCPB comparison"
```

---

## Self-review checklist (run by the implementing agent before declaring done)

- [ ] All 16 task headers are checked off in this file.
- [ ] `pytest tests/install -v` is green on all platforms (skip-mark on per-OS service tests is fine).
- [ ] `pytest tests/unit/install -v` is green.
- [ ] `pytest tests/unit -v` is green (regressions in non-install code).
- [ ] `python scripts/build_mcpb.py && python scripts/check_mcpb_consistency.py` exit 0.
- [ ] `bash -n scripts/install.sh` exits 0.
- [ ] `piighost install --mode=full --vault-dir=/tmp/vt --clients=code --embedder=local --yes` on a clean env writes `~/.claude/settings.json` correctly.
- [ ] `piighost install --mode=mcp-only --clients=code --yes` writes settings.json **without** ANTHROPIC_BASE_URL.
- [ ] `piighost install --mode=light --clients=code --yes` prints the deprecation warning.
- [ ] `piighost connect` / `piighost disconnect` toggle ANTHROPIC_BASE_URL without touching `mcpServers`.
- [ ] `piighost doctor` exits non-zero when BASE_URL is set and proxy is unreachable.

If any of the above fails, do NOT mark this plan complete. Open a follow-up task or fix in place.

## Out of scope (deliberate)

- Fixing strict-mode's mitmproxy `regular` vs `transparent` mismatch.
- Reranker / detector backend selection in the interactive flow.
- Telemetry / audit log retention policy.
- The `piighost config` command surface (referenced in error messages but its implementation is its own spec).
- Generic ansible-style plan replay (`InstallPlan` is structured to support this later).
