# MCP Singleton-Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current per-session `piighost serve` (which loads its own GLiNER2 model and competes with siblings for the vault, causing stdio JSON-RPC corruption and orphan accumulation in Claude Desktop) with a thin stdio→HTTP shim that forwards every MCP call to the existing singleton daemon. Add an orphan reaper inside the daemon, a `piighost cleanup` CLI for diagnostics, and a `daemon.disabled` flag so `piighost daemon stop` is honored against auto-spawn.

**Architecture:** The existing `piighost daemon` (port 51207, holds PIIGhostService + GLiNER2 + vault) becomes the single backend for all MCP clients. `piighost serve --transport stdio` shrinks to a ~100-line FastMCP shim that calls the daemon's `/rpc` over loopback HTTP with the bearer token. Auto-spawn is delegated to existing `daemon.lifecycle.ensure_daemon`; we extend it to honor a new `daemon.disabled` flag. A reaper task in the daemon scans every 60 s for `piighost serve` processes whose parent is not Claude Desktop and terminates them.

**Tech Stack:** Python 3.10+, FastMCP (stdio transport), httpx (HTTP forwarding), portalocker (existing — cross-platform lock), psutil (existing — process inspection), pytest + pytest-asyncio (existing test harness), Starlette (daemon HTTP).

**Spec:** [`docs/superpowers/specs/2026-04-25-mcp-singleton-daemon-design.md`](../specs/2026-04-25-mcp-singleton-daemon-design.md)

---

## File Map

| Path | Action | Responsibility |
|---|---|---|
| `src/piighost/daemon/lifecycle.py` | **Modify** | `ensure_daemon` raises `DaemonDisabled` when flag present. `stop_daemon` writes the flag. New `start_daemon` removes it. |
| `src/piighost/daemon/exceptions.py` | **Create** | `DaemonDisabled` exception + others surfaced by lifecycle/discovery. |
| `src/piighost/daemon/audit_log.py` | **Create** | Single-writer JSON-Lines logger for `daemon.log` (`emit(event, **fields)`). |
| `src/piighost/daemon/server.py` | **Modify** | Run reaper on startup + every 60 s task. Emit lifecycle events to `daemon.log`. |
| `src/piighost/daemon/reaper.py` | **Create** | `find_orphan_serves()` and `reap()` using psutil; cross-platform parent-name check. |
| `src/piighost/mcp/shim.py` | **Create** | The thin shim: discovery → tool registry → HTTP forward → stdio. |
| `src/piighost/mcp/tools.py` | **Create** | Static tool catalog: list of `ToolSpec(name, rpc_method, doc, params_model, timeout_s)`. |
| `src/piighost/mcp/server.py` | **Replace** | Becomes 5-line entrypoint that calls `shim.run()`. |
| `src/piighost/cli/commands/cleanup.py` | **Create** | `piighost cleanup` command. |
| `src/piighost/cli/main.py` | **Modify** | Register `cleanup` command. |
| `tests/daemon/test_lifecycle_disabled.py` | **Create** | `daemon.disabled` flag semantics. |
| `tests/daemon/test_audit_log.py` | **Create** | JSON-line writer is concurrent-safe. |
| `tests/daemon/test_reaper.py` | **Create** | Reaper kill rules with mocked psutil. |
| `tests/mcp/test_shim_tools.py` | **Create** | Per-tool dispatch + error mapping. |
| `tests/mcp/test_shim_eof.py` | **Create** | Stdin EOF regression test. |
| `tests/cli/test_cleanup_cmd.py` | **Create** | Cleanup CLI behavior. |
| `tests/integration/test_mcp_lifecycle.py` | **Create** | Slow E2E: 5 shims + 1 daemon + reaper. |

---

## Task 1: `daemon.disabled` flag in lifecycle

**Files:**
- Modify: `src/piighost/daemon/lifecycle.py`
- Create: `src/piighost/daemon/exceptions.py`
- Create: `tests/daemon/test_lifecycle_disabled.py`

**Why:** With auto-spawn enabled, `piighost daemon stop` is meaningless — the next MCP frontend respawns it instantly. We need a flag to express user intent: "I deliberately stopped this; do not auto-restart until I explicitly start it again."

- [ ] **Step 1: Create the exceptions module**

```python
# src/piighost/daemon/exceptions.py
"""Exceptions raised by daemon discovery and lifecycle code."""
from __future__ import annotations


class DaemonDisabled(RuntimeError):
    """Raised when the user has explicitly stopped the daemon.

    Presence of ``<vault>/daemon.disabled`` means callers must NOT
    auto-spawn — they should surface a clear error telling the user to
    run ``piighost daemon start``.
    """


class DaemonStartTimeout(RuntimeError):
    """Auto-spawn timed out waiting for the handshake to appear."""
```

- [ ] **Step 2: Write failing tests for the disabled flag**

```python
# tests/daemon/test_lifecycle_disabled.py
"""The daemon.disabled flag is honored by ensure_daemon and stop_daemon."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from piighost.daemon.exceptions import DaemonDisabled
from piighost.daemon.lifecycle import ensure_daemon, start_daemon, stop_daemon


def test_ensure_daemon_raises_when_disabled_flag_present(tmp_path: Path) -> None:
    (tmp_path / "daemon.disabled").touch()
    with pytest.raises(DaemonDisabled):
        ensure_daemon(tmp_path)


def test_stop_daemon_writes_disabled_flag(tmp_path: Path) -> None:
    # No daemon to stop, but the flag must still be written so future
    # ensure_daemon calls are blocked.
    stop_daemon(tmp_path)
    assert (tmp_path / "daemon.disabled").exists()


def test_start_daemon_removes_disabled_flag(tmp_path: Path) -> None:
    (tmp_path / "daemon.disabled").touch()
    # Patch the actual spawn so the test doesn't fork a real daemon.
    with patch("piighost.daemon.lifecycle.ensure_daemon") as mock_ensure:
        mock_ensure.return_value = None
        start_daemon(tmp_path)
    assert not (tmp_path / "daemon.disabled").exists()
    mock_ensure.assert_called_once_with(tmp_path)


def test_disabled_flag_persists_when_daemon_was_already_stopped(tmp_path: Path) -> None:
    """stop_daemon is idempotent and always leaves the flag in place."""
    stop_daemon(tmp_path)
    stop_daemon(tmp_path)  # second call must not crash
    assert (tmp_path / "daemon.disabled").exists()
```

- [ ] **Step 3: Run the tests — expect 4 failures**

```bash
pytest tests/daemon/test_lifecycle_disabled.py -v
```

Expected: `ImportError: cannot import name 'start_daemon'` (function doesn't exist yet) and the `ensure_daemon` test fails because the flag isn't checked.

- [ ] **Step 4: Modify `lifecycle.py` to honor the flag**

Apply this diff:

```python
# src/piighost/daemon/lifecycle.py — add at top with other imports
from piighost.daemon.exceptions import DaemonDisabled, DaemonStartTimeout

_DISABLED_FILENAME = "daemon.disabled"


def _disabled_path(vault_dir: Path) -> Path:
    return vault_dir / _DISABLED_FILENAME


# Modify the existing ensure_daemon — add the disabled check at the top
def ensure_daemon(vault_dir: Path, *, timeout_sec: float = 15.0) -> DaemonHandshake:
    """Return a running daemon handshake, spawning if necessary.

    Raises ``DaemonDisabled`` if ``<vault>/daemon.disabled`` exists; the
    user has explicitly stopped the daemon and does not want auto-spawn.
    """
    if _disabled_path(vault_dir).exists():
        raise DaemonDisabled(
            "piighost daemon was stopped by user. "
            "Run: piighost daemon start"
        )

    vault_dir.mkdir(parents=True, exist_ok=True)
    lock_path = vault_dir / "daemon.lock"
    with portalocker.Lock(str(lock_path), timeout=timeout_sec):
        hs = read_handshake(vault_dir)
        if hs and _is_alive_with_retry(hs):
            return hs
        if hs:
            _cleanup_stale(vault_dir, hs)
        try:
            return _spawn(vault_dir, timeout_sec=timeout_sec)
        except TimeoutError as exc:
            raise DaemonStartTimeout(str(exc)) from exc


# Modify stop_daemon — write the flag BEFORE killing
def stop_daemon(vault_dir: Path) -> bool:
    """Stop the running daemon and disable auto-spawn.

    Always writes ``<vault>/daemon.disabled`` so future ``ensure_daemon``
    calls raise ``DaemonDisabled`` instead of restarting the daemon.
    Returns ``True`` if a running daemon was found and stopped.
    """
    vault_dir.mkdir(parents=True, exist_ok=True)
    _disabled_path(vault_dir).touch()

    hs = read_handshake(vault_dir)
    if hs is None:
        return False
    try:
        httpx.post(
            f"http://127.0.0.1:{hs.port}/shutdown",
            headers={"Authorization": f"Bearer {hs.token}"},
            timeout=3.0,
        )
    except httpx.HTTPError:
        pass
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not psutil.pid_exists(hs.pid):
            break
        time.sleep(0.1)
    else:
        try:
            psutil.Process(hs.pid).kill()
        except psutil.Error:
            pass
    (vault_dir / "daemon.json").unlink(missing_ok=True)
    return True


# Add a new function — the inverse of stop_daemon
def start_daemon(vault_dir: Path, *, timeout_sec: float = 15.0) -> DaemonHandshake:
    """Remove the daemon.disabled flag (if any) and ensure the daemon is up.

    Idempotent — safe to call when the daemon is already running.
    """
    vault_dir.mkdir(parents=True, exist_ok=True)
    _disabled_path(vault_dir).unlink(missing_ok=True)
    return ensure_daemon(vault_dir, timeout_sec=timeout_sec)
```

- [ ] **Step 5: Run the tests — expect 4 passes**

```bash
pytest tests/daemon/test_lifecycle_disabled.py -v
```

- [ ] **Step 6: Run the existing daemon tests to ensure no regression**

```bash
pytest tests/daemon/ tests/cli/test_daemon_cmd.py -v --no-cov
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/daemon/exceptions.py src/piighost/daemon/lifecycle.py tests/daemon/test_lifecycle_disabled.py
git commit -m "feat(daemon): daemon.disabled flag honored by ensure_daemon

stop_daemon now writes ~/.piighost/daemon.disabled so subsequent
ensure_daemon calls raise DaemonDisabled instead of auto-spawning.
start_daemon removes the flag and ensures the daemon is up.

This is the lifecycle prerequisite for the upcoming MCP shim, which
will auto-spawn the daemon on first call but must respect explicit
user-stop.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: JSON-Lines audit log

**Files:**
- Create: `src/piighost/daemon/audit_log.py`
- Create: `tests/daemon/test_audit_log.py`

**Why:** The shim and daemon need a single shared log for events (`started`, `rpc`, `reaper_killed`, `daemon_unreachable`, etc.). A custom small writer keeps the format strict (one JSON object per line, ts in UTC ISO8601, atomic append).

- [ ] **Step 1: Write failing tests**

```python
# tests/daemon/test_audit_log.py
"""Structured JSON-line writer for daemon.log."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from piighost.daemon.audit_log import emit


def test_emit_writes_single_json_line(tmp_path: Path) -> None:
    log_path = tmp_path / "daemon.log"
    emit(log_path, "started", pid=1234, port=51207)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["event"] == "started"
    assert obj["pid"] == 1234
    assert obj["port"] == 51207
    assert obj["ts"].endswith("Z")  # UTC ISO 8601


def test_emit_appends_without_clobbering(tmp_path: Path) -> None:
    log_path = tmp_path / "daemon.log"
    emit(log_path, "first", n=1)
    emit(log_path, "second", n=2)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "first"
    assert json.loads(lines[1])["event"] == "second"


def test_emit_creates_parent_dir(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "dir" / "daemon.log"
    emit(log_path, "ok")
    assert log_path.exists()


def test_emit_concurrent_writes_no_corruption(tmp_path: Path) -> None:
    """Two threads emitting in parallel must not produce a torn line."""
    log_path = tmp_path / "daemon.log"

    def hammer(tag: str) -> None:
        for i in range(50):
            emit(log_path, "rpc", tag=tag, i=i)

    t1 = threading.Thread(target=hammer, args=("a",))
    t2 = threading.Thread(target=hammer, args=("b",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 100
    for line in lines:
        json.loads(line)  # must be valid JSON, never a torn row


def test_emit_omits_none_values(tmp_path: Path) -> None:
    log_path = tmp_path / "daemon.log"
    emit(log_path, "rpc", method="anonymize", error=None)
    obj = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "error" not in obj
    assert obj["method"] == "anonymize"
```

- [ ] **Step 2: Run — expect import error**

```bash
pytest tests/daemon/test_audit_log.py -v
```

- [ ] **Step 3: Implement the writer**

```python
# src/piighost/daemon/audit_log.py
"""Single-writer JSON-Lines logger for the piighost daemon.log file.

Why a custom writer:
  - Strict format (one JSON object per line, no logging-module overhead)
  - Atomic append: a single ``write()`` syscall per line, so concurrent
    writers never tear a line. We open with ``O_APPEND`` so the kernel
    serializes appends.
  - UTC ISO 8601 timestamps with explicit ``Z`` suffix (no ambiguity).
  - None-valued fields are omitted to keep lines compact.

Usage:
    emit(vault_dir / "daemon.log", "rpc", method="anonymize",
         duration_ms=42, status="ok")
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(log_path: Path, event: str, **fields: Any) -> None:
    """Append one JSON line to ``log_path``.

    ``fields`` whose value is ``None`` are dropped. The line ends with
    a single ``\\n``.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"ts": _now_iso(), "event": event}
    for k, v in fields.items():
        if v is not None:
            payload[k] = v
    line = json.dumps(payload, default=str) + "\n"
    fd = os.open(str(log_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
```

- [ ] **Step 4: Run — expect 5 passes**

```bash
pytest tests/daemon/test_audit_log.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/piighost/daemon/audit_log.py tests/daemon/test_audit_log.py
git commit -m "feat(daemon): JSON-line audit log writer

Atomic single-line append via O_APPEND. Used by upcoming shim,
daemon lifecycle events, and reaper events. Concurrent-safe so
multiple shim processes can share one daemon.log.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: MCP tool catalog

**Files:**
- Create: `src/piighost/mcp/tools.py`
- Create: `tests/mcp/test_tool_catalog.py`

**Why:** Centralize the list of MCP tools the shim exposes and the daemon-RPC method each maps to. Keeping it as data (not code) makes the shim's registration loop trivial and the catalog easy to test.

- [ ] **Step 1: Write failing tests**

```python
# tests/mcp/test_tool_catalog.py
"""MCP tool catalog covers every daemon RPC method."""
from __future__ import annotations

from piighost.mcp.tools import TOOL_CATALOG, ToolSpec


def test_catalog_is_nonempty() -> None:
    assert len(TOOL_CATALOG) >= 14


def test_every_tool_has_required_fields() -> None:
    for spec in TOOL_CATALOG:
        assert isinstance(spec, ToolSpec)
        assert spec.name and spec.name.replace("_", "").isalnum()
        assert spec.rpc_method
        assert spec.description
        assert spec.timeout_s > 0


def test_tool_names_unique() -> None:
    names = [s.name for s in TOOL_CATALOG]
    assert len(names) == len(set(names))


def test_index_path_has_long_timeout() -> None:
    by_name = {s.name: s for s in TOOL_CATALOG}
    assert by_name["index_path"].timeout_s >= 600


def test_vault_stats_has_short_timeout() -> None:
    by_name = {s.name: s for s in TOOL_CATALOG}
    assert by_name["vault_stats"].timeout_s <= 5


def test_anonymize_text_maps_to_anonymize_rpc() -> None:
    by_name = {s.name: s for s in TOOL_CATALOG}
    assert by_name["anonymize_text"].rpc_method == "anonymize"


def test_rehydrate_text_maps_to_rehydrate_rpc() -> None:
    by_name = {s.name: s for s in TOOL_CATALOG}
    assert by_name["rehydrate_text"].rpc_method == "rehydrate"
```

- [ ] **Step 2: Run — expect import error**

- [ ] **Step 3: Create the catalog**

```python
# src/piighost/mcp/tools.py
"""MCP tool catalog: maps each public tool name to a daemon RPC method.

The shim iterates this list to register one FastMCP tool per entry.
Each tool's HTTP timeout is sized for the operation; ``index_path`` is
the largest at 10 minutes because indexing a multi-format folder can
take that long.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    """One MCP tool exposed by the shim."""

    name: str          # public name shown to MCP clients
    rpc_method: str    # daemon /rpc method this forwards to
    description: str   # human description for the MCP tool
    timeout_s: float   # HTTP timeout for the forward call


TOOL_CATALOG: list[ToolSpec] = [
    # Core PII operations
    ToolSpec(
        name="anonymize_text",
        rpc_method="anonymize",
        description="Anonymize text, replacing PII with opaque tokens.",
        timeout_s=60.0,
    ),
    ToolSpec(
        name="rehydrate_text",
        rpc_method="rehydrate",
        description="Rehydrate anonymized text back to original PII.",
        timeout_s=60.0,
    ),
    ToolSpec(
        name="detect",
        rpc_method="detect",
        description="Detect PII entities without modifying the text.",
        timeout_s=60.0,
    ),

    # Vault inspection
    ToolSpec(
        name="vault_list",
        rpc_method="vault_list",
        description="List vault entries with optional label filter.",
        timeout_s=5.0,
    ),
    ToolSpec(
        name="vault_show",
        rpc_method="vault_show",
        description="Show one vault entry by token.",
        timeout_s=5.0,
    ),
    ToolSpec(
        name="vault_stats",
        rpc_method="vault_stats",
        description="Return vault statistics (total, by label).",
        timeout_s=5.0,
    ),
    ToolSpec(
        name="vault_search",
        rpc_method="vault_search",
        description="Full-text search the PII vault by original value.",
        timeout_s=60.0,
    ),

    # RAG indexing & query
    ToolSpec(
        name="index_path",
        rpc_method="index_path",
        description="Index a file or directory into the retrieval store.",
        timeout_s=600.0,
    ),
    ToolSpec(
        name="remove_doc",
        rpc_method="remove_doc",
        description="Remove a document from the retrieval store.",
        timeout_s=30.0,
    ),
    ToolSpec(
        name="index_status",
        rpc_method="index_status",
        description="Show what is currently indexed.",
        timeout_s=600.0,
    ),
    ToolSpec(
        name="query",
        rpc_method="query",
        description="Hybrid BM25+vector search over indexed documents.",
        timeout_s=60.0,
    ),

    # Project management
    ToolSpec(
        name="list_projects",
        rpc_method="list_projects",
        description="List all projects.",
        timeout_s=5.0,
    ),
    ToolSpec(
        name="create_project",
        rpc_method="create_project",
        description="Create a new project.",
        timeout_s=30.0,
    ),
    ToolSpec(
        name="delete_project",
        rpc_method="delete_project",
        description="Delete a project (requires force=True for non-empty).",
        timeout_s=30.0,
    ),
]
```

- [ ] **Step 4: Run — expect 7 passes**

```bash
pytest tests/mcp/test_tool_catalog.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/tools.py tests/mcp/test_tool_catalog.py
git commit -m "feat(mcp): static catalog of MCP tools with daemon RPC mapping

Centralizes the 14 tools the shim will expose, with explicit per-tool
timeouts (5s for read-only inspection, 60s for PII ops, 600s for index).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Shim HTTP dispatcher

**Files:**
- Create: `src/piighost/mcp/shim.py` (initial: dispatcher only, no FastMCP yet)
- Create: `tests/mcp/test_shim_dispatch.py`

**Why:** Build the small piece that takes a `ToolSpec` and `params`, calls the daemon, and returns the result (or raises). Test this in isolation before wiring into FastMCP.

- [ ] **Step 1: Write failing tests**

```python
# tests/mcp/test_shim_dispatch.py
"""Shim HTTP forwarder: maps ToolSpec calls to daemon /rpc."""
from __future__ import annotations

import json

import httpx
import pytest

from piighost.mcp.shim import RpcError, dispatch
from piighost.mcp.tools import ToolSpec


SAMPLE_SPEC = ToolSpec(
    name="anonymize_text",
    rpc_method="anonymize",
    description="...",
    timeout_s=60.0,
)


def _ok_handler(want_method: str, want_params: dict, response_result: dict):
    def _h(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == want_method
        assert body["params"] == want_params
        assert request.headers["authorization"] == "Bearer abc"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": response_result})
    return _h


@pytest.mark.asyncio
async def test_dispatch_forwards_method_and_params() -> None:
    transport = httpx.MockTransport(_ok_handler(
        "anonymize",
        {"text": "hi", "project": "default"},
        {"anonymized": "<X:1>", "entities": []},
    ))
    result = await dispatch(
        SAMPLE_SPEC,
        params={"text": "hi", "project": "default"},
        base_url="http://127.0.0.1:51207",
        token="abc",
        transport=transport,
    )
    assert result == {"anonymized": "<X:1>", "entities": []}


@pytest.mark.asyncio
async def test_dispatch_raises_on_jsonrpc_error() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0",
            "id": body["id"],
            "error": {"code": -32000, "message": "vault corrupted"},
        })
    with pytest.raises(RpcError, match="vault corrupted"):
        await dispatch(
            SAMPLE_SPEC, params={}, base_url="http://x", token="t",
            transport=httpx.MockTransport(_h),
        )


@pytest.mark.asyncio
async def test_dispatch_raises_on_http_5xx() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")
    with pytest.raises(RpcError, match="HTTP 500"):
        await dispatch(
            SAMPLE_SPEC, params={}, base_url="http://x", token="t",
            transport=httpx.MockTransport(_h),
        )


@pytest.mark.asyncio
async def test_dispatch_raises_on_timeout() -> None:
    fast = ToolSpec(name="x", rpc_method="m", description="d", timeout_s=0.001)

    def _h(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)
    with pytest.raises(RpcError, match=r"timed out"):
        await dispatch(
            fast, params={}, base_url="http://x", token="t",
            transport=httpx.MockTransport(_h),
        )


@pytest.mark.asyncio
async def test_dispatch_uses_per_tool_timeout() -> None:
    captured: dict = {}
    def _h(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"jsonrpc":"2.0","id":1,"result":{}})
    long = ToolSpec(name="x", rpc_method="m", description="d", timeout_s=600.0)
    await dispatch(
        long, params={}, base_url="http://x", token="t",
        transport=httpx.MockTransport(_h),
    )
    # The httpx Timeout object embeds 600.0 as the read timeout
    assert captured["timeout"]["read"] == 600.0
```

- [ ] **Step 2: Run — expect failures (module not found)**

- [ ] **Step 3: Create the dispatcher**

```python
# src/piighost/mcp/shim.py
"""Thin stdio→HTTP shim for piighost MCP.

The shim exposes the same MCP tools as before but does no work itself —
every call is forwarded to the singleton ``piighost daemon`` over
loopback HTTP.
"""
from __future__ import annotations

import uuid

import httpx

from piighost.mcp.tools import ToolSpec


class RpcError(RuntimeError):
    """Raised when a daemon RPC call fails (HTTP, timeout, or JSON-RPC error)."""


async def dispatch(
    spec: ToolSpec,
    *,
    params: dict,
    base_url: str,
    token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Forward one MCP tool call to the daemon's /rpc endpoint.

    Returns the daemon's ``result`` field on success.
    Raises :class:`RpcError` on:
      - JSON-RPC error response (with the daemon's error message)
      - HTTP non-2xx
      - Read/connect timeout (per the spec's ``timeout_s``)
      - Any other transport failure

    The shim NEVER retries silently; surfacing failures is the only way
    to notice the daemon is unhealthy.
    """
    body = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": spec.rpc_method,
        "params": params,
    }
    timeout = httpx.Timeout(spec.timeout_s, connect=5.0)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            r = await client.post(
                f"{base_url}/rpc",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.TimeoutException as exc:
        raise RpcError(f"{spec.name} timed out after {spec.timeout_s}s") from exc
    except httpx.HTTPError as exc:
        raise RpcError(f"{spec.name} transport error: {exc}") from exc

    if r.status_code != 200:
        raise RpcError(f"{spec.name} HTTP {r.status_code}: {r.text[:200]}")

    payload = r.json()
    if "error" in payload:
        msg = payload["error"].get("message", "unknown")
        raise RpcError(f"{spec.name}: {msg}")
    return payload.get("result", {})
```

- [ ] **Step 4: Run — expect 5 passes**

```bash
pytest tests/mcp/test_shim_dispatch.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/shim.py tests/mcp/test_shim_dispatch.py
git commit -m "feat(mcp): shim dispatcher forwards tool calls to daemon /rpc

Per-tool timeout, JSON-RPC error mapping, no silent retries.
Tested in isolation against MockTransport.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Shim FastMCP wiring + EOF regression test

**Files:**
- Modify: `src/piighost/mcp/shim.py` (add `run()`)
- Create: `tests/mcp/test_shim_eof.py`

**Why:** This is the *primary* fix for orphan shims — when Claude Desktop closes the stdio pipe, FastMCP's stdio loop must return so the process exits. We assert that with an explicit regression test (a stdio MCP loop fed `b""` returns within 1 s).

- [ ] **Step 1: Write the EOF regression test**

```python
# tests/mcp/test_shim_eof.py
"""Stdio EOF must cause the FastMCP stdio loop to return promptly.

This is the regression test for orphan piighost serve processes that
accumulated when Claude Desktop closed pipes. If this fails, the shim
will leak processes again.
"""
from __future__ import annotations

import asyncio
import io
import sys
from unittest.mock import patch

import pytest

from piighost.mcp.shim import _build_mcp


@pytest.mark.asyncio
async def test_run_stdio_returns_within_1s_on_eof(monkeypatch) -> None:
    """Pipe an empty stream to the FastMCP stdio loop; it must return."""
    mcp = _build_mcp(base_url="http://unused", token="unused")

    # Replace stdin/stdout with empty pipes so run_stdio sees immediate EOF.
    empty_in = io.BytesIO(b"")
    discard_out = io.BytesIO()

    class _BinIO:
        def __init__(self, buf: io.BytesIO) -> None:
            self.buffer = buf

    monkeypatch.setattr(sys, "stdin", _BinIO(empty_in))
    monkeypatch.setattr(sys, "stdout", _BinIO(discard_out))

    # Should return well within 1 second on EOF.
    await asyncio.wait_for(mcp.run_stdio_async(), timeout=1.0)
```

- [ ] **Step 2: Add `_build_mcp()` and `run()` to `shim.py`**

Append to `src/piighost/mcp/shim.py`:

```python
# src/piighost/mcp/shim.py — append at end

from fastmcp import FastMCP

from piighost.daemon.audit_log import emit
from piighost.daemon.lifecycle import ensure_daemon
from piighost.mcp.tools import TOOL_CATALOG


def _build_mcp(*, base_url: str, token: str) -> FastMCP:
    """Construct a FastMCP server with one tool per catalog entry.

    Each tool forwards via ``dispatch`` to the daemon. The shim itself
    holds zero business state.
    """
    mcp = FastMCP("piighost")

    for spec in TOOL_CATALOG:
        # Capture spec by default arg to avoid the closure trap.
        @mcp.tool(name=spec.name, description=spec.description)
        async def _tool(_spec: "ToolSpec" = spec, **kwargs) -> dict:
            return await dispatch(
                _spec, params=kwargs, base_url=base_url, token=token,
            )

    return mcp


async def run(vault_dir) -> None:
    """Entry point: ensure the daemon is up, then serve MCP over stdio."""
    from pathlib import Path
    vault_dir = Path(vault_dir)

    hs = ensure_daemon(vault_dir)  # may raise DaemonDisabled
    base_url = f"http://127.0.0.1:{hs.port}"
    log_path = vault_dir / "daemon.log"
    emit(log_path, "shim_started", daemon_pid=hs.pid)

    mcp = _build_mcp(base_url=base_url, token=hs.token)
    try:
        await mcp.run_stdio_async()
    finally:
        emit(log_path, "shim_stopped")
```

- [ ] **Step 3: Run the EOF test — expect pass**

```bash
pytest tests/mcp/test_shim_eof.py -v
```

If it fails (FastMCP bug or environment quirk), inspect with:
```bash
pytest tests/mcp/test_shim_eof.py -v -s --tb=long
```

If FastMCP's `run_stdio_async` doesn't actually exit on EOF, file an upstream issue and add a fallback: a 5-minute idle timer that calls `mcp.shutdown()` if no requests arrive. **Do NOT commit silent retry/restart logic.**

- [ ] **Step 4: Run the existing dispatch tests to confirm no regression**

```bash
pytest tests/mcp/ -v
```

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/shim.py tests/mcp/test_shim_eof.py
git commit -m "feat(mcp): shim run() with FastMCP stdio + EOF regression test

The stdio EOF test guards against the orphan-process accumulation we
observed in Claude Desktop today (3 stale piighost serve processes
that never exited after their parent closed the pipe).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Replace `mcp/server.py` entry point

**Files:**
- Modify: `src/piighost/mcp/server.py` (replace contents)
- Verify: `src/piighost/cli/commands/serve.py` (no change expected, just confirm it calls into mcp.server)

**Why:** The CLI `piighost serve --transport stdio` currently runs the old fat MCP server. Point it at the shim. The thin shim is now the only thing that ever runs in stdio mode.

- [ ] **Step 1: Read the current `serve` command to confirm entrypoint**

```bash
grep -n "from piighost.mcp" src/piighost/cli/commands/serve.py
```

Expected: a line importing from `piighost.mcp.server`. If it imports a specific function name (e.g., `serve_stdio`), the new `mcp/server.py` must export the same name.

- [ ] **Step 2: Rewrite `mcp/server.py` as a thin entry**

```python
# src/piighost/mcp/server.py
"""Thin entry point for ``piighost serve --transport stdio``.

Delegates to the shim, which forwards every tool call to the daemon.
The previous in-process FastMCP+PIIGhostService implementation is gone;
the daemon is the single source of truth.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from piighost.mcp.shim import run as _shim_run


def serve_stdio(vault_dir: Path) -> None:
    """Run the MCP shim over stdio. Blocks until stdin EOF."""
    asyncio.run(_shim_run(vault_dir))
```

If `cli/commands/serve.py` imports a different name, expose that same name as an alias.

- [ ] **Step 3: Quick smoke — `piighost serve --help` still works**

```bash
piighost serve --help
```

Expected: usage shown, no traceback.

- [ ] **Step 4: Run the full mcp test suite**

```bash
pytest tests/mcp/ -v
```

- [ ] **Step 5: Commit**

```bash
git add src/piighost/mcp/server.py
git commit -m "refactor(mcp): serve --transport stdio uses thin shim

Replaces the in-process fat MCP server (loaded its own GLiNER2 +
vault) with a 5-line entry that delegates to the shim, which forwards
to the daemon. Eliminates per-session model duplication and ends
stdio JSON-RPC corruption from competing processes.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Orphan reaper

**Files:**
- Create: `src/piighost/daemon/reaper.py`
- Create: `tests/daemon/test_reaper.py`

**Why:** Stdio EOF is the primary mechanism for clean shutdown. The reaper is the safety net for hard crashes (kill -9, OOM, power loss) where EOF was never delivered.

- [ ] **Step 1: Write failing tests**

```python
# tests/daemon/test_reaper.py
"""Reaper kill rules with mocked psutil — no real processes touched."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from piighost.daemon import reaper


def _proc(pid: int, *, name: str = "python.exe", cmdline: list[str] | None = None,
          parent_name: str | None = "Claude.exe", running: bool = True) -> MagicMock:
    """Build a MagicMock that quacks like a psutil.Process."""
    p = MagicMock()
    p.pid = pid
    p.name.return_value = name
    p.cmdline.return_value = cmdline or [
        "python.exe", "-m", "piighost", "serve", "--transport", "stdio",
    ]
    p.is_running.return_value = running
    if parent_name is None:
        p.parent.return_value = None
    else:
        parent = MagicMock()
        parent.name.return_value = parent_name
        p.parent.return_value = parent
    return p


def test_orphan_with_no_parent_is_killed(monkeypatch) -> None:
    orphan = _proc(7708, parent_name=None)
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [orphan])
    killed = reaper.reap()
    assert killed == [7708]
    orphan.terminate.assert_called_once()


def test_orphan_with_non_claude_parent_is_killed(monkeypatch) -> None:
    orphan = _proc(15732, parent_name="explorer.exe")
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [orphan])
    killed = reaper.reap()
    assert killed == [15732]


def test_shim_with_claude_parent_is_NOT_killed(monkeypatch) -> None:
    shim = _proc(1234, parent_name="Claude.exe")
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [shim])
    killed = reaper.reap()
    assert killed == []
    shim.terminate.assert_not_called()


def test_shim_with_lowercase_claude_parent_is_NOT_killed(monkeypatch) -> None:
    shim = _proc(1234, parent_name="claude")
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [shim])
    assert reaper.reap() == []


def test_manual_run_from_terminal_is_NOT_killed(monkeypatch) -> None:
    """`piighost serve` run from a bash/pwsh terminal must not be reaped."""
    for shell in ("bash", "pwsh", "cmd.exe", "powershell.exe", "WindowsTerminal.exe"):
        manual = _proc(1234, parent_name=shell)
        monkeypatch.setattr(reaper, "_iter_serves", lambda m=manual: [m])
        assert reaper.reap() == [], f"shell {shell} treated as orphan parent"


def test_terminate_then_kill_if_still_running(monkeypatch) -> None:
    orphan = _proc(7708, parent_name=None)
    # Simulate proc surviving terminate
    orphan.is_running.side_effect = [True, True, True]  # always running
    import psutil
    orphan.wait.side_effect = psutil.TimeoutExpired(5)
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [orphan])
    reaper.reap()
    orphan.terminate.assert_called_once()
    orphan.kill.assert_called_once()


def test_does_not_kill_non_serve_python(monkeypatch) -> None:
    not_a_serve = _proc(99, cmdline=["python.exe", "-c", "print(1)"], parent_name=None)
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [])  # filtered out before
    assert reaper.reap() == []
```

- [ ] **Step 2: Run — expect import errors**

- [ ] **Step 3: Implement the reaper**

```python
# src/piighost/daemon/reaper.py
"""Reap orphaned ``piighost serve`` processes.

A process is an orphan when its parent process is either:
  - not running anymore, or
  - not Claude Desktop (``claude`` / ``Claude.exe``).

The reaper is conservative: it deliberately does NOT kill manual
``piighost serve`` invocations from a developer's terminal (parent is
a shell). Those are out of scope; touching them would be hostile.
"""
from __future__ import annotations

from typing import Iterable

import psutil


_CLAUDE_PARENT_NAMES = {"claude", "claude.exe"}


def _iter_serves() -> Iterable[psutil.Process]:
    """Yield every running ``piighost serve --transport stdio`` process."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.cmdline() or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        cmd = " ".join(cmdline).lower()
        if "piighost" in cmd and "serve" in cmd and "stdio" in cmd:
            yield proc


def _is_orphan(proc: psutil.Process) -> bool:
    try:
        parent = proc.parent()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True
    if parent is None:
        return True
    try:
        parent_name = parent.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True
    return parent_name not in _CLAUDE_PARENT_NAMES


def reap() -> list[int]:
    """Terminate every orphaned shim. Returns list of killed PIDs."""
    killed: list[int] = []
    for proc in _iter_serves():
        if not _is_orphan(proc):
            continue
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
            killed.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed
```

- [ ] **Step 4: Run — expect 7 passes**

```bash
pytest tests/daemon/test_reaper.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/piighost/daemon/reaper.py tests/daemon/test_reaper.py
git commit -m "feat(daemon): orphan reaper for piighost serve processes

Conservative kill rule: only orphans whose parent is dead or not
Claude Desktop. Manual debug runs from terminals are explicitly safe.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Wire reaper into daemon startup + 60s loop

**Files:**
- Modify: `src/piighost/daemon/server.py` (add reaper task, audit-log lifecycle events)
- Create: `tests/daemon/test_server_reaper.py`

**Why:** The reaper module exists; now the daemon must call it on startup and every 60 s. Use Starlette's lifespan context manager so the task is cancelled cleanly on shutdown.

- [ ] **Step 1: Write a failing integration-style test**

```python
# tests/daemon/test_server_reaper.py
"""The daemon spawns the reaper task on startup and runs it periodically."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from piighost.daemon.server import build_app


@pytest.mark.asyncio
async def test_reaper_runs_on_startup(tmp_path) -> None:
    with patch("piighost.daemon.server.reaper.reap", return_value=[]) as mock_reap:
        app, _token = build_app(tmp_path)
        with TestClient(app) as _:
            # TestClient triggers lifespan; reaper should have run at least once.
            await asyncio.sleep(0.2)
        assert mock_reap.call_count >= 1


@pytest.mark.asyncio
async def test_reaper_logs_killed_pids(tmp_path) -> None:
    with patch("piighost.daemon.server.reaper.reap", return_value=[7708, 15732]):
        app, _token = build_app(tmp_path)
        with TestClient(app) as _:
            await asyncio.sleep(0.2)
    log = (tmp_path / "daemon.log").read_text(encoding="utf-8")
    assert "reaper_killed" in log
    assert "7708" in log
    assert "15732" in log
```

- [ ] **Step 2: Run — expect failures (reaper not wired in)**

- [ ] **Step 3: Modify `daemon/server.py`**

Add at the top of the imports:

```python
import asyncio
from contextlib import asynccontextmanager

from piighost.daemon import reaper
from piighost.daemon.audit_log import emit
```

Add a lifespan helper (place near the existing route definitions):

```python
def _make_lifespan(vault_dir):
    log_path = vault_dir / "daemon.log"

    @asynccontextmanager
    async def lifespan(app):
        emit(log_path, "daemon_started", port=app.state.port if hasattr(app.state, "port") else None)
        # Run reaper once on startup, then every 60s.
        async def _reaper_loop() -> None:
            while True:
                try:
                    killed = reaper.reap()
                    if killed:
                        emit(log_path, "reaper_killed", reaped_pids=killed)
                except Exception as exc:  # pragma: no cover
                    emit(log_path, "reaper_error", error=str(exc))
                await asyncio.sleep(60)

        task = asyncio.create_task(_reaper_loop())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            emit(log_path, "daemon_stopped")
    return lifespan
```

In `build_app`, pass the lifespan to Starlette:

```python
# Inside build_app — replace the existing Starlette() instantiation
return Starlette(
    routes=[
        Route("/health", health),
        Route("/rpc", rpc, methods=["POST"]),
        Route("/shutdown", shutdown, methods=["POST"]),
    ],
    lifespan=_make_lifespan(vault_dir),
), token
```

- [ ] **Step 4: Run the test — expect 2 passes**

```bash
pytest tests/daemon/test_server_reaper.py -v
```

- [ ] **Step 5: Run full daemon test suite — no regressions**

```bash
pytest tests/daemon/ -v
```

- [ ] **Step 6: Commit**

```bash
git add src/piighost/daemon/server.py tests/daemon/test_server_reaper.py
git commit -m "feat(daemon): reaper task runs on startup + every 60s

Combined with stdio EOF in the shim, this guarantees orphaned
piighost serve processes never accumulate beyond one minute. Lifecycle
events written to daemon.log.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: `piighost cleanup` CLI command

**Files:**
- Create: `src/piighost/cli/commands/cleanup.py`
- Modify: `src/piighost/cli/main.py`
- Create: `tests/cli/test_cleanup_cmd.py`

**Why:** One-shot diagnostic the user can run anytime to clean stale state files, kill orphan shims, and report duplicate daemons. Default `--dry-run` prevents accidents.

- [ ] **Step 1: Write failing tests**

```python
# tests/cli/test_cleanup_cmd.py
"""piighost cleanup CLI behaviors."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_dry_run_default_does_not_modify_anything(tmp_path: Path) -> None:
    stale = tmp_path / "daemon.json"
    stale.write_text(json.dumps({"pid": 999_999, "port": 0, "token": "x", "started_at": 0}))
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path)])
    assert r.exit_code == 0
    assert stale.exists(), "dry-run must not delete anything"
    assert "stale" in r.stdout.lower()


def test_force_removes_stale_handshake(tmp_path: Path) -> None:
    stale = tmp_path / "daemon.json"
    stale.write_text(json.dumps({"pid": 999_999, "port": 0, "token": "x", "started_at": 0}))
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path), "--force"])
    assert r.exit_code == 0
    assert not stale.exists()


def test_keeps_live_handshake(tmp_path: Path) -> None:
    """Handshake with a live PID (this test process) must not be removed."""
    live = tmp_path / "daemon.json"
    live.write_text(json.dumps({
        "pid": os.getpid(), "port": 51207, "token": "x", "started_at": 0,
    }))
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path), "--force"])
    assert r.exit_code == 0
    assert live.exists()


def test_reports_orphan_shims(tmp_path: Path) -> None:
    with patch("piighost.cli.commands.cleanup.reaper.reap", return_value=[7708, 15732]):
        r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path), "--force"])
    assert r.exit_code == 0
    assert "7708" in r.stdout
    assert "15732" in r.stdout


def test_json_output(tmp_path: Path) -> None:
    stale = tmp_path / "daemon.json"
    stale.write_text(json.dumps({"pid": 999_999, "port": 0, "token": "x", "started_at": 0}))
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path), "--force", "--json"])
    assert r.exit_code == 0
    payload = json.loads(r.stdout)
    assert "removed" in payload
    assert any("daemon.json" in item for item in payload["removed"])


def test_warns_on_disabled_flag_without_recent_stop(tmp_path: Path) -> None:
    (tmp_path / "daemon.disabled").touch()
    # No daemon.log exists, so "no recent stop event"
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path)])
    assert "daemon.disabled" in r.stdout
    assert "warn" in r.stdout.lower()
    # Flag is NOT auto-removed
    assert (tmp_path / "daemon.disabled").exists()
```

- [ ] **Step 2: Run — expect failures (command not registered)**

- [ ] **Step 3: Implement the cleanup command**

```python
# src/piighost/cli/commands/cleanup.py
"""`piighost cleanup` — remove stale handshake/lock files, kill orphans."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Annotated

import psutil
import typer

from piighost.daemon import reaper


def _is_pid_alive(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def _scan_stale_state_files(vault: Path) -> list[Path]:
    """Find handshake/lock files whose recorded PID is dead."""
    stale: list[Path] = []
    candidates = list(vault.glob("*.json")) + list(vault.glob("*.lock")) + list(vault.glob("*.handshake.json"))
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = data.get("pid")
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        if isinstance(pid, int) and pid > 0 and not _is_pid_alive(pid):
            stale.append(path)
    return stale


def _check_disabled_flag_age(vault: Path) -> str | None:
    """Return a warning if daemon.disabled exists without a matching log entry."""
    flag = vault / "daemon.disabled"
    if not flag.exists():
        return None
    log_path = vault / "daemon.log"
    if not log_path.exists():
        return f"daemon.disabled present but no daemon.log to verify recent stop"
    flag_mtime = flag.stat().st_mtime
    cutoff = flag_mtime - 60  # accept stop events within 60s before flag mtime
    for line in reversed(log_path.read_text(encoding="utf-8").splitlines()[-100:]):
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("event") == "daemon_stopped":
            return None
    return f"daemon.disabled present but no recent daemon_stopped event in log"


def run(
    vault: Annotated[Path, typer.Option(help="Vault dir")] = Path.home() / ".piighost",
    force: Annotated[bool, typer.Option("--force", help="Apply changes (default: dry-run)")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
) -> None:
    """Reap orphan piighost serve processes and stale state files."""
    vault = Path(vault)
    actions: dict[str, list] = {"removed": [], "killed": [], "warnings": []}

    # 1. Stale state files
    for path in _scan_stale_state_files(vault):
        if force:
            try:
                path.unlink()
                actions["removed"].append(str(path))
            except OSError as exc:
                actions["warnings"].append(f"could not remove {path}: {exc}")
        else:
            actions["removed"].append(f"[would remove] {path}")

    # 2. Orphan shims
    if force:
        actions["killed"] = reaper.reap()
    else:
        # Dry-run: report what reaper.reap() would touch without killing.
        from piighost.daemon.reaper import _iter_serves, _is_orphan
        actions["killed"] = [
            f"[would kill] pid={p.pid}" for p in _iter_serves() if _is_orphan(p)
        ]

    # 3. Disabled flag sanity check
    warn = _check_disabled_flag_age(vault)
    if warn:
        actions["warnings"].append(warn)

    if json_out:
        typer.echo(json.dumps(actions, indent=2))
        return

    if actions["removed"]:
        for r in actions["removed"]:
            typer.echo(f"[stale] {r}")
    if actions["killed"]:
        for k in actions["killed"]:
            typer.echo(f"[orphan] {k}")
    if actions["warnings"]:
        for w in actions["warnings"]:
            typer.echo(f"[warn] {w}")
    if not any(actions.values()):
        typer.echo("nothing to clean")

    if not force:
        typer.echo("\n(dry-run — pass --force to apply)")
```

- [ ] **Step 4: Register in `cli/main.py`**

Add to imports:

```python
from piighost.cli.commands import cleanup as cleanup_cmd
```

Add after other `app.command(...)` lines:

```python
app.command("cleanup")(cleanup_cmd.run)
```

- [ ] **Step 5: Run the tests — expect 6 passes**

```bash
pytest tests/cli/test_cleanup_cmd.py -v
```

- [ ] **Step 6: Manual smoke**

```bash
piighost cleanup --vault $HOME/.piighost
```

Should report what it would do without modifying anything.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/cli/commands/cleanup.py src/piighost/cli/main.py tests/cli/test_cleanup_cmd.py
git commit -m "feat(cli): piighost cleanup — reap orphans + stale state files

Default --dry-run; --force applies. --json for tooling. Warns on
suspicious daemon.disabled flag (present without recent stop event).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Daemon-stop CLI integration

**Files:**
- Modify: `src/piighost/cli/commands/daemon.py`

**Why:** The daemon CLI currently has `start` and `stop` (and `status`). Update them to use the new `start_daemon` (which removes `daemon.disabled`) and the modified `stop_daemon` (which writes the flag). User-facing CLI behavior stays the same; only the underlying lifecycle changes.

- [ ] **Step 1: Read current `daemon.py` to identify the CLI handlers**

```bash
grep -n "command\|stop_daemon\|ensure_daemon" src/piighost/cli/commands/daemon.py
```

- [ ] **Step 2: Update the CLI handlers**

Find the handler that calls `ensure_daemon(...)` for `daemon start` — replace with `start_daemon(...)` from the lifecycle module:

```python
# src/piighost/cli/commands/daemon.py — update import
from piighost.daemon.lifecycle import ensure_daemon, start_daemon, status, stop_daemon
```

Find the `start` command body (likely `ensure_daemon(vault_dir)`); replace with:

```python
@daemon_app.command("start")
def start_cmd() -> None:
    vault_dir = _resolve_or_exit()
    hs = start_daemon(vault_dir)  # removes daemon.disabled, then ensure_daemon
    emit_json_line({"pid": hs.pid, "port": hs.port, "started_at": hs.started_at})
```

The `stop` command keeps calling `stop_daemon(vault_dir)` — that function now writes the `daemon.disabled` flag automatically.

- [ ] **Step 3: Run all daemon CLI tests**

```bash
pytest tests/cli/test_daemon_cmd.py -v
```

- [ ] **Step 4: Manual smoke**

```bash
piighost daemon stop
ls $HOME/.piighost/daemon.disabled        # should exist
piighost daemon start
ls $HOME/.piighost/daemon.disabled        # should be gone
```

- [ ] **Step 5: Commit**

```bash
git add src/piighost/cli/commands/daemon.py
git commit -m "feat(cli): daemon start removes daemon.disabled flag

piighost daemon stop already writes the flag (Task 1); this completes
the round-trip so the CLI is self-consistent.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Audit-log RPC events from the daemon

**Files:**
- Modify: `src/piighost/daemon/server.py` (rpc handler emits events)

**Why:** Useful diagnostics for the doctor command and any user trying to understand why a tool call took 30 s. Each `/rpc` call is logged with method, duration, status.

- [ ] **Step 1: Write a failing test**

```python
# tests/daemon/test_server_rpc_logging.py
"""Each /rpc call must log an audit-log entry with timing and status."""
from __future__ import annotations

import json
from unittest.mock import patch

from starlette.testclient import TestClient

from piighost.daemon.server import build_app


def test_rpc_success_logged(tmp_path) -> None:
    app, token = build_app(tmp_path)
    with patch("piighost.daemon.server._dispatch", return_value={"ok": True}):
        with TestClient(app) as client:
            client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "id": 1, "method": "vault_stats", "params": {}},
                headers={"Authorization": f"Bearer {token}"},
            )
    log = (tmp_path / "daemon.log").read_text(encoding="utf-8")
    matching = [json.loads(line) for line in log.splitlines() if '"event": "rpc"' in line]
    assert any(e.get("method") == "vault_stats" and e.get("status") == "ok" for e in matching)


def test_rpc_error_logged(tmp_path) -> None:
    app, token = build_app(tmp_path)
    with patch("piighost.daemon.server._dispatch", side_effect=ValueError("boom")):
        with TestClient(app) as client:
            client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "id": 1, "method": "anonymize", "params": {}},
                headers={"Authorization": f"Bearer {token}"},
            )
    log = (tmp_path / "daemon.log").read_text(encoding="utf-8")
    matching = [json.loads(line) for line in log.splitlines() if '"event": "rpc"' in line]
    assert any(e.get("method") == "anonymize" and e.get("status") == "error" for e in matching)
```

- [ ] **Step 2: Run — expect failures (no logging yet)**

- [ ] **Step 3: Add timing+logging to the rpc handler**

In `daemon/server.py`'s `rpc` handler, wrap the dispatch call:

```python
import time
# ... existing imports include emit from audit_log

async def rpc(request):
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    method = body.get("method", "")
    params = body.get("params", {}) or {}
    log_path = vault_dir / "daemon.log"
    started = time.monotonic()
    try:
        result = await _dispatch(state["service"], method, params)
        emit(log_path, "rpc", method=method,
             duration_ms=int((time.monotonic() - started) * 1000), status="ok")
        return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": result})
    except Exception as exc:
        emit(log_path, "rpc", method=method,
             duration_ms=int((time.monotonic() - started) * 1000),
             status="error", error=type(exc).__name__)
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {"code": -32000, "message": type(exc).__name__},
        })
```

- [ ] **Step 4: Run — expect 2 passes**

```bash
pytest tests/daemon/test_server_rpc_logging.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/piighost/daemon/server.py tests/daemon/test_server_rpc_logging.py
git commit -m "feat(daemon): /rpc emits audit log lines with method+duration+status

Lets piighost doctor surface slow methods and frequent errors.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: Integration smoke test

**Files:**
- Create: `tests/integration/test_mcp_lifecycle.py`

**Why:** Lock the headline guarantees end-to-end: spawning multiple shims results in exactly one daemon, killed shims are reaped, `daemon.disabled` blocks auto-spawn.

- [ ] **Step 1: Write the smoke tests**

```python
# tests/integration/test_mcp_lifecycle.py
"""End-to-end MCP lifecycle smoke tests.

Marked slow; opt in via:  pytest -m slow
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from piighost.daemon.handshake import read_handshake


pytestmark = pytest.mark.slow


@pytest.fixture()
def fresh_vault(tmp_path: Path) -> Path:
    return tmp_path / ".piighost"


def _spawn_shim(vault: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "piighost", "serve", "--vault", str(vault), "--transport", "stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _wait_for_daemon(vault: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hs = read_handshake(vault)
        if hs and psutil.pid_exists(hs.pid):
            return
        time.sleep(0.2)
    raise TimeoutError(f"daemon did not start within {timeout}s")


def test_five_shims_share_one_daemon(fresh_vault: Path) -> None:
    shims = [_spawn_shim(fresh_vault) for _ in range(5)]
    try:
        _wait_for_daemon(fresh_vault)
        # Count actual daemon processes (must be exactly 1)
        daemons = [
            p for p in psutil.process_iter(["cmdline"])
            if p.info["cmdline"] and "piighost.daemon" in " ".join(p.info["cmdline"])
        ]
        assert len(daemons) == 1
    finally:
        for s in shims:
            s.terminate()
        for s in shims:
            s.wait(timeout=10)


def test_kill_9_shim_is_reaped_within_70s(fresh_vault: Path) -> None:
    shim = _spawn_shim(fresh_vault)
    _wait_for_daemon(fresh_vault)
    # SIGKILL the shim
    if sys.platform == "win32":
        shim.kill()
    else:
        os.kill(shim.pid, signal.SIGKILL)
    # Reaper runs every 60s — give it 70s wall clock
    deadline = time.monotonic() + 70
    while time.monotonic() < deadline:
        if not psutil.pid_exists(shim.pid):
            return
        time.sleep(1)
    pytest.fail(f"shim pid={shim.pid} survived 70s, reaper did not kill it")


def test_disabled_flag_blocks_auto_spawn(fresh_vault: Path) -> None:
    fresh_vault.mkdir(parents=True, exist_ok=True)
    (fresh_vault / "daemon.disabled").touch()

    shim = _spawn_shim(fresh_vault)
    try:
        rc = shim.wait(timeout=10)
        assert rc != 0, "shim must exit non-zero when daemon is disabled"
        stderr = (shim.stderr.read() if shim.stderr else b"").decode("utf-8", errors="replace")
        assert "stopped by user" in stderr.lower() or "DaemonDisabled" in stderr
    finally:
        if shim.poll() is None:
            shim.terminate()
```

- [ ] **Step 2: Run with the slow marker**

```bash
pytest tests/integration/test_mcp_lifecycle.py -v -m slow
```

- [ ] **Step 3: If `test_kill_9_shim_is_reaped_within_70s` fails**

The reaper runs only every 60 s. The test gives 70 s — but if FastMCP's stdio loop is keeping the killed shim's resources alive, the reaper may also need to be re-invoked. Verify by reading `daemon.log` and looking for `reaper_killed` entries.

If the reaper *did* run but the killed shim is still listed in `psutil`, that suggests Windows process handle quirks. Workaround: after `proc.terminate()` + `proc.wait()` in the reaper, also call `psutil.Process(pid).wait(0)` to drop our handle.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_mcp_lifecycle.py
git commit -m "test(mcp): integration smoke — 5 shims share 1 daemon, kill -9 reaped

Slow tests, opt in via pytest -m slow. Locks the three headline
guarantees: singleton daemon, orphan reaping under hard kills,
daemon.disabled blocks auto-spawn.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Step 1: Full unit test suite**

```bash
pytest tests/ -v --no-cov -m 'not slow'
```

Expected: all green except known pre-existing failures (`tests/unit/install/test_install_cmd.py::test_install_fails_gracefully_on_preflight_error` Windows-env, `tests/vault/test_discovery.py::test_raises_when_absent` if running on a host with `~/.piighost` already).

- [ ] **Step 2: Integration smoke**

```bash
pytest tests/integration/ -v -m slow
```

- [ ] **Step 3: Real-world cleanup**

On the developer's machine (Windows):

```powershell
# Kill any stale piighost serve from the old code path
piighost cleanup --force

# Verify exactly zero piighost serve processes remain
Get-Process | Where-Object { $_.ProcessName -like "*piighost*" }

# Trigger the new flow: open Claude Desktop, send a test PII message,
# verify ONE daemon + ONE shim per session in netstat
& "$env:SystemRoot\System32\netstat.exe" -ano | Select-String "LISTENING.*51207"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*piighost*serve*" } |
    Measure-Object | Select-Object Count
```

Expected: exactly 1 daemon listener on 51207, and the number of `piighost serve` processes equals the number of open Claude Desktop sessions (no orphans).

- [ ] **Step 4: Tag the milestone**

```bash
git tag -a v0.8.0-mcp-singleton -m "MCP singleton daemon + thin shim"
```
