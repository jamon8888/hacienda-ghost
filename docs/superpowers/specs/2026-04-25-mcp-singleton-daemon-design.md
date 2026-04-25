# MCP Singleton-Daemon Design

**Date:** 2026-04-25
**Status:** Approved for implementation planning
**Scope:** piighost MCP transport reliability + process lifecycle hygiene

## Problem statement

In production today, three failure modes compound to break the MCP integration in Claude Desktop:

1. **Process explosion.** Claude Desktop launches `piighost serve --transport stdio` once per session. Each instance loads its own GLiNER2 model (~200 MB RAM, ~10 s warmup) and opens its own connection to the vault SQLite. We observed 3 stale `piighost serve` processes (pids 7708, 15732, 3900) plus 2 `uv run` wrappers (pids 16288, 14316) accumulated in a single working day.
2. **Stdio JSON-RPC corruption.** Each `piighost serve` shares its stdout with the JSON-RPC protocol channel. Concurrent processes competing for the same vault, plus model-loading progress bars from gliner2 leaking past `_harden_stdio_channel`, intermittently corrupt the stream. Claude Desktop reports tool calls as "rejected" / "Server transport closed unexpectedly".
3. **No orphan reaping.** When a Claude Desktop session ends (window closed, crash, kill -9), the spawned `piighost serve` does not exit. Instances accumulate indefinitely. Manual cleanup requires Task Manager.

These compound: a single `index_path` call may spawn the model in three competing processes, blow stdio, and fail with a generic rejection.

## Goals

1. **At most one daemon process** holding the heavy state (model, vault, embeddings, project registry) regardless of how many Claude Desktop sessions are open.
2. **MCP tool calls succeed reliably on the first try** — no rejections, no timeouts, no flake.
3. **Orphan processes never accumulate** — stdio EOF triggers clean exit; the daemon actively reaps any stragglers.
4. **Backward compatible** — `.mcp.json` and plugin manifests unchanged. The MCP tool surface (names, params) stays identical.

## Non-goals

- Performance work beyond eliminating duplicate model loads.
- Changes to the proxy daemon (separate component on port 8443).
- Changes to PIIGhostService internals (the existing daemon already exposes a clean `/rpc` API).
- Fixing the `PIIGhostService.active_project` bug — that is in the proxy code path and is its own commit.
- Multi-host deployment. Single-machine, loopback-only.

## Architecture

```
                            ┌─────────────────────────┐
                            │  piighost daemon        │
                            │  (singleton, port 51207)│
   Claude Desktop ──┐       │  ─ holds PIIGhostService│
                    │       │  ─ holds GLiNER2 model  │
                    │       │  ─ owns vault SQLite    │
   Claude Desktop ──┼──┐    │  ─ /rpc + /health       │
                    │  │    └────────────▲────────────┘
                    │  │                 │ loopback HTTP
                    ▼  ▼                 │ Bearer token
            ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
            │ piighost serve │  │ piighost serve │  │ piighost serve │
            │ (stdio frontend│  │ (stdio frontend│  │ (stdio frontend│
            │  per session)  │  │  per session)  │  │  per session)  │
            └───────┬────────┘  └───────┬────────┘  └───────┬────────┘
                    │ JSON-RPC stdio    │                   │
                 Claude Desktop      Claude Desktop      Claude Desktop
                 session #1          session #2          session #3
```

Each `piighost serve` becomes a thin stdio→HTTP shim. It speaks MCP/JSON-RPC over stdio with Claude Desktop and forwards every method call to the daemon's `/rpc` endpoint. The daemon stays warm with the model loaded; spawning N sessions costs N × ~10 MB shims, not N × ~200 MB.

The shim contains no business logic — it only adapts transports.

## Components

### 1. The thin MCP shim (`piighost.mcp.shim`)

Replaces today's `piighost.mcp.server`. Approximately 100 lines.

**Responsibilities:**

1. Discover or auto-start the daemon (see §Lifecycle).
2. Build a FastMCP server with one tool per daemon RPC method (anonymize, rehydrate, detect, vault_*, index_path, query, etc).
3. For each tool call, forward to the daemon's `/rpc` over loopback HTTP with the daemon's bearer token.
4. Speak stdio JSON-RPC with Claude Desktop until stdin EOF, then exit.

**Pseudocode of the per-tool handler:**

```python
@mcp.tool(name=method_name, description=method_doc)
async def _tool(**kwargs) -> dict:
    body = {
        "jsonrpc": "2.0",
        "id": uuid4().hex,
        "method": method_rpc_name,
        "params": kwargs,
    }
    async with httpx.AsyncClient(timeout=method_timeout) as client:
        r = await client.post(
            f"{base_url}/rpc",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        result = r.json()
        if "error" in result:
            raise McpError(message=result["error"]["message"])
        return result["result"]
```

**The shim does NOT:**

- Load PIIGhostService.
- Load GLiNER2.
- Touch vault SQLite.
- Spawn child processes (other than possibly the daemon, exactly once, see Lifecycle).
- Hold any persistent state between calls.

**Per-tool timeouts** are explicit and honest:

| Tool | Timeout |
|------|---------|
| `vault_stats`, `vault_list`, `vault_show`, `daemon_status`, `list_projects` | 5 s |
| `anonymize_text`, `rehydrate_text`, `detect`, `vault_search` | 60 s |
| `query` | 60 s |
| `index_path`, `index_status` | 600 s |
| `create_project`, `delete_project`, `remove_doc` | 30 s |

### 2. Daemon discovery and auto-start (`piighost.daemon.discovery`)

A small, focused module shared by the shim and any other client of the daemon (CLI commands, the proxy daemon if it ever wants to call back).

**State files in `~/.piighost/`:**

| File | Purpose |
|------|---------|
| `daemon.json` (existing) | `{pid, port, token, started_at}` written by daemon at startup |
| `daemon.lock` (new) | `{pid, started_at}` of the spawner; atomically created via `os.O_EXCL` |
| `daemon.disabled` (new) | Empty marker file; presence means "user explicitly stopped daemon — frontends must NOT auto-spawn" |

**`ensure_daemon_reachable() -> (base_url, token)`:**

```
1. If daemon.disabled exists → raise DaemonDisabled (clean error, no spawn)
2. If daemon.json exists:
     a. ping http://127.0.0.1:{port}/health with the bearer token
     b. on 200 → return (base_url, token)  ← happy path, ~5 ms
3. Try to atomically create daemon.lock with os.O_EXCL:
     a. If we got the lock → spawn daemon (detached process), wait up to 30 s
        for daemon.json to appear and /health to return 200, then release lock
     b. If lock exists with live PID → wait up to 30 s for daemon.json to
        appear, then ping. If still missing, raise DaemonStartTimeout.
     c. If lock exists with dead PID → remove it and goto 3a.
4. Return (base_url, token)
```

**Spawning the daemon detached:**

- Windows: `subprocess.Popen([python, "-m", "piighost.daemon", "--vault", ...], creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, stdout=DEVNULL, stderr=open("daemon.log", "ab"))`
- Linux/macOS: `subprocess.Popen([...], start_new_session=True, stdout=DEVNULL, stderr=open("daemon.log", "ab"))`

Daemon's stderr is preserved to `~/.piighost/daemon.log` (append) so spawn failures are diagnosable.

### 3. Orphan reaper (in the daemon)

Runs on daemon startup and every 60 s thereafter via `asyncio.create_task(_reaper_loop())`.

**Conservative kill rule:**

```python
async def reap_orphans():
    me = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline", "ppid"]):
        if proc.pid == me:
            continue
        if not _is_piighost_serve(proc):
            continue
        parent = proc.parent() if proc.is_running() else None
        if parent is None or parent.name().lower() not in {"claude.exe", "claude"}:
            log.info("reaping orphan", pid=proc.pid, parent=str(parent))
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
```

`_is_piighost_serve(proc)` matches by command line containing `piighost` and `serve` and `--transport stdio`. It deliberately does **not** match users running `piighost serve` manually from a terminal whose parent is `bash`/`pwsh`/`cmd` — those are explicitly out of scope and never killed.

### 4. `piighost cleanup` CLI command

Module: `piighost.cli.commands.cleanup`. One-shot diagnostic.

**Flags:**
- `--dry-run` (default true): report what would be done, take no action
- `--force`: actually do it
- `--json`: machine-readable output

**Operations, in order:**

1. **Stale state files.** Scan `~/.piighost/` for `*.lock`, `*.handshake.json`, `*.json` named like daemon/proxy descriptors. Parse each, check the recorded PID. If PID is dead, remove the file.
2. **Orphaned shims.** Same psutil walk as the reaper, but reports + acts on `--force`.
3. **Duplicate daemons.** If more than one `python -m piighost.daemon` exists, keep the one whose PID matches `daemon.json`. Kill the rest.
4. **Suspicious `daemon.disabled`.** If the flag exists but no recent `daemon stop` log entry, surface a warning (don't auto-remove).

**Output (text mode):**
```
Scanning ~/.piighost/...
[stale]   removed daemon.lock (pid 4004 dead)
[stale]   removed proxy.handshake.json (port 443 no listener)
[orphan]  killed pid=7708 (parent process gone)
[orphan]  killed pid=15732 (parent not Claude.exe)
[ok]      1 daemon, 0 duplicates
[warn]    daemon.disabled present but no recent stop in log — left in place
4 actions, 1 warning.
```

**Exit codes:**
- 0 = clean (or nothing to do in --dry-run)
- 1 = warnings only
- 2 = errors during cleanup

### 5. Lifecycle of `piighost daemon stop`

Today, `piighost daemon stop` kills the daemon. With auto-spawn introduced, that becomes a foot-gun (any frontend immediately respawns).

**New behavior:**

```
1. Atomically write daemon.disabled (empty file).
2. Send SIGTERM (or POST /shutdown) to the daemon.
3. Wait up to 5 s for clean exit; SIGKILL if needed.
4. Remove daemon.json and daemon.lock.
5. Log {"event":"daemon_stopped","by":"user","ts":...} to daemon.log.
```

**`piighost daemon start`:**

```
1. Remove daemon.disabled (if present).
2. If daemon already running → print status and exit 0.
3. Spawn the daemon (same code path as the shim's auto-spawn).
4. Wait for /health → 200, print pid+port.
```

## Data flow

**Happy path: anonymize via Claude Desktop**

```
Claude Desktop  ── stdio JSON-RPC ──►  piighost serve (shim)
                                              │
                                              ├─ ensure_daemon_reachable()
                                              │  → (base_url, token) from daemon.json
                                              │
                                              ├─ POST /rpc {"method": "anonymize", "params": {...}}
                                              │  with Authorization: Bearer <token>
                                              ▼
                                         piighost daemon
                                              │
                                              ├─ PIIGhostService.anonymize(...)
                                              ├─ GLiNER2 inference (already-warm model)
                                              ├─ vault writes
                                              │
                                              ◄── 200 OK {"result": {...}}
                                              │
Claude Desktop  ◄── stdio JSON-RPC ──  shim returns result
```

Total added latency vs today: one loopback HTTP roundtrip (~1–3 ms). Removed: model loading time per shim (~10–30 s) since the daemon is warm.

## Error handling

| Failure | Shim behavior | User sees |
|---|---|---|
| `daemon.disabled` exists | `ensure_daemon_reachable` raises `DaemonDisabled` immediately | MCP tool error: `"piighost daemon was stopped by user. Run: piighost daemon start"` |
| Daemon down, auto-spawn fails | Capture spawn stderr to `daemon.log`; raise `DaemonSpawnFailed` | MCP tool error: `"piighost daemon failed to start. Run: piighost doctor"` |
| Daemon up, RPC returns `{"error": {...}}` | Wrap in `McpError` | MCP tool error with daemon's error message verbatim |
| Daemon HTTP 5xx | Wrap in `McpError`, do NOT retry | MCP tool error: `"piighost daemon error (HTTP 500). See ~/.piighost/daemon.log"` |
| Daemon HTTP timeout | Wrap in `McpError`, do NOT kill daemon | MCP tool error: `"piighost {method} timed out after {N}s"` |
| Daemon TCP refused mid-call | Wrap in `McpError`. Next call will trigger auto-spawn fresh | MCP tool error: `"piighost daemon connection lost (will auto-restart on next call)"` |

The shim **never silently retries**. Silent retries hide bugs. The next user action triggers a fresh attempt which auto-spawns if needed.

## Testing

### Unit tests (no real daemon, no real subprocess)

**`tests/mcp/test_shim_dispatch.py`:**
- For each registered tool, mock httpx, assert correct RPC method + params + bearer token are sent.
- Test all 5 error paths above with mocked HTTP responses.
- Pipe `b""` to a stub stdio MCP loop and assert the function returns within 1 s. *Regression test for the EOF-not-propagated bug.*

**`tests/mcp/test_discovery.py`:**
- `daemon.json` present + `/health` ok → returns directly without spawn.
- `daemon.json` present + `/health` 401 → raises `DaemonAuthFailed` (caught → user sees clear error).
- `daemon.json` missing + lock acquired → spawns; daemon.json appears within 30 s; returns.
- `daemon.json` missing + lock held by live PID → waits, ultimately succeeds.
- `daemon.json` missing + lock held by dead PID → removes lock, takes it, spawns.
- `daemon.disabled` present → raises `DaemonDisabled` without checking anything else.

**`tests/mcp/test_reaper.py`:**
- Mock `psutil.process_iter` returning fake processes.
- Assert orphans (parent dead or non-claude) are killed.
- Assert valid shims (parent = claude.exe) are NOT killed.
- Assert the daemon never kills itself.
- Assert manual debug runs (parent = bash/pwsh/cmd) are NOT killed.

### Integration tests (real subprocess, fake daemon)

**`tests/mcp/test_lifecycle.py`** (slow marker, opt-in):
- Spawn 5 shims simultaneously → exactly one daemon process exists in `pgrep` output.
- Kill the daemon → next shim call returns clean error → next-next call auto-spawns successfully.
- Set `daemon.disabled` → all shim calls error without spawn → remove flag → calls work.
- Kill a shim's "parent" (the test's stub) → wait 70 s → assert daemon's reaper killed the orphaned shim.

### End-to-end smoke (CI)

**`tests/mcp/test_smoke.py`:**
- Start daemon → run `piighost cleanup --dry-run` → assert empty report.
- Run a full anonymize → vault_stats round-trip via the shim.
- Spawn 5 shims, kill them with SIGKILL → wait 70 s → assert daemon log contains 5 reap events.

### Cleanup CLI tests

**`tests/cli/test_cleanup.py`:**
- Stale lock with dead PID → reported (dry-run) / removed (force).
- Orphan shim → reported / killed.
- Multiple daemons → keep one, report others.
- `daemon.disabled` without recent stop → warning, no removal.
- `--json` flag produces parseable output.

## Observability

Single structured-log file `~/.piighost/daemon.log`, one JSON object per line.

**Standard fields:** `ts, src, level, event, pid` (always present).

**Per-event fields:** vary by event type.

**Examples:**
```json
{"ts":"2026-04-25T18:05:01Z","src":"shim","level":"info","event":"started","pid":1234,"daemon_pid":11880,"shim_id":"a1b2"}
{"ts":"2026-04-25T18:05:02Z","src":"shim","level":"info","event":"rpc","pid":1234,"shim_id":"a1b2","method":"anonymize","duration_ms":42,"status":"ok"}
{"ts":"2026-04-25T18:05:03Z","src":"daemon","level":"warn","event":"reaper_killed","pid":11880,"reaped_pids":[7708,15732]}
{"ts":"2026-04-25T18:05:04Z","src":"shim","level":"warn","event":"daemon_unreachable","pid":1234,"action":"auto_spawn"}
{"ts":"2026-04-25T18:05:35Z","src":"daemon","level":"info","event":"started","pid":11880,"port":51207,"vault":"C:\\Users\\NMarchitecte\\.piighost"}
{"ts":"2026-04-25T18:30:00Z","src":"daemon","level":"info","event":"daemon_stopped","pid":11880,"by":"user"}
```

`piighost doctor` reads the last 200 lines and surfaces:
- Frequent `reaper_killed` events → possible crash loop, suggests checking child crash cause
- Slow `rpc` durations (p99 > expected) → perf regression flag
- Repeated `daemon_unreachable` → suggests the daemon is unstable

## Migration

The shim swap is invisible to existing `.mcp.json` files. The launch command stays:

```json
"command": "uvx",
"args": ["--from", "piighost[gliner2] @ git+...", "piighost", "serve", "--transport", "stdio"]
```

But — see §Lifecycle Layer 1 — `uv run` / `uvx` reportedly swallows EOF on Windows. As part of this change, plugin authors are encouraged (in the README) to switch to invoking the entry-point script directly:

```json
"command": "piighost",
"args": ["serve", "--transport", "stdio"]
```

(Or via `uv tool run piighost serve --transport stdio` which has cleaner signal propagation than `uvx --from … piighost`.)

This is an *opportunistic* migration, not a hard requirement. The new shim's stdio-EOF unit test ensures the regression doesn't return regardless of launcher.

## File map (informational, not a plan)

| Path | Action | Responsibility |
|------|--------|----------------|
| `src/piighost/mcp/server.py` | **Replace** | Old: full FastMCP+service. New: thin shim that forwards to daemon. |
| `src/piighost/mcp/shim.py` | **Create** | Shim dispatcher: per-tool HTTP forwarder. |
| `src/piighost/daemon/discovery.py` | **Create** | `ensure_daemon_reachable`, lock+handshake handling, detached spawn. |
| `src/piighost/daemon/reaper.py` | **Create** | Orphan scanner used by daemon's startup + 60s loop. |
| `src/piighost/daemon/server.py` | **Modify** | Add reaper loop, write structured logs to daemon.log. |
| `src/piighost/daemon/lifecycle.py` | **Modify** | `daemon stop` writes `daemon.disabled`; `daemon start` removes it. |
| `src/piighost/cli/commands/cleanup.py` | **Create** | `piighost cleanup` command. |
| `src/piighost/cli/main.py` | **Modify** | Register `cleanup` command. |
| `tests/mcp/test_shim_dispatch.py` | Create | Per-tool dispatch + EOF regression. |
| `tests/mcp/test_discovery.py` | Create | Lock/handshake state machine. |
| `tests/mcp/test_reaper.py` | Create | Reaper kill rules. |
| `tests/mcp/test_lifecycle.py` | Create | Slow integration tests. |
| `tests/cli/test_cleanup.py` | Create | Cleanup CLI behaviors. |

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Daemon becomes a SPOF — its crash kills all sessions | Auto-spawn on next call. Daemon process is supervised by the system service manager (existing scheduled task / systemd / launchd). |
| Lock file race on slow filesystems (e.g. networked home dir) | `os.O_EXCL` is atomic on local filesystems. Document that `~/.piighost/` must be local. |
| Daemon stderr eats disk if it crash-loops | `daemon.log` rotated weekly with size cap (separate concern, ship with sane default). |
| Reaper kills a shim during an in-flight call | Only orphans get killed (parent dead). A shim with a live Claude Desktop parent is never reaped, even if a call is hung. |
| psutil unavailable on some platforms | psutil is already a hard dependency of piighost (per pyproject.toml). |

## Out of scope (explicitly)

- The proxy daemon (port 8443) and its `active_project` bug.
- Cross-machine MCP / remote daemon.
- Replacing fastmcp.
- Changing the daemon's `/rpc` protocol.
- Authentication beyond loopback bearer token.
- A GUI or systray for managing the daemon.
