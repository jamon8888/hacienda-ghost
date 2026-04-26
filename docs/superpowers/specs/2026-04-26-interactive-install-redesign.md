# Interactive Install Redesign

**Date:** 2026-04-26
**Status:** Design approved, awaiting implementation plan
**Author:** Claude (with NMarchitecte)

## Goal

Replace the env-var-driven `scripts/install.{sh,ps1}` + `piighost install --mode=light|strict` UX with an interactive flow built around two named modes — **Full** (anonymizing proxy + MCP tools + RAG/extraction) and **MCP-only** (MCP tools + RAG/extraction, no proxy).

The redesign must:

- Be safe by default — never break the system-wide `api.anthropic.com` connection.
- Detect installed Claude clients (Code, Desktop) and let the user pick which to register the MCP server in.
- Remain scriptable from CI / `curl | bash` via flags.
- Coexist with the existing standalone MCPB distribution channel without merging the two.
- Provide CLI escape hatches so users never have to hand-edit JSON to recover.

## Background

### Current state

| Surface | Behavior |
|---------|----------|
| `scripts/install.{sh,ps1}` | Env-var-driven (`PIIGHOST_MODE`, `PIIGHOST_EXTRAS`). Default mode: `strict`. Bootstraps `uv` then calls `piighost install --mode=$MODE`. |
| `piighost install --mode=light` | Generates CA + leaf cert at `~/.piighost/proxy/`. Writes `ANTHROPIC_BASE_URL=https://localhost:8443` into `~/.claude/settings.json`. Proxy is per-app, opt-in. No admin needed. |
| `piighost install --mode=strict` | CA for `api.anthropic.com` + adds `127.0.0.1 api.anthropic.com` to hosts file + installs background service binding `:443`. Transparent system-wide intercept. Requires admin. |
| `piighost install --mode=<other>` | Legacy: preflight + docker/uv + Claude Desktop MCP entry. Reachable only via undocumented mode strings. |
| MCPB bundles (`bundles/{core,full}/`) | Standalone Claude Desktop drag-drop extensions. Built by `scripts/build_mcpb.py` to `dist/mcpb/piighost-{core,full}.mcpb`. Never include the proxy (Desktop extensions can't bind privileged ports). |

### Failure modes of strict mode (the reason for the redesign)

Strict mode can take down **all** Anthropic API traffic on the machine, not just piighost's:

1. **Proxy daemon stops/crashes** — hosts file says `127.0.0.1 api.anthropic.com`, nothing on `:443`, every Claude API call across the OS gets `ECONNREFUSED`.
2. **Port :443 contention** — another process holds `:443`, daemon can't bind.
3. **CA missing from trust store** — TLS handshake fails with `UNTRUSTED_CERT`.
4. **Architectural mismatch** — mitmproxy is launched in `mode=["regular"]` (explicit forward proxy expecting `CONNECT api.anthropic.com:443`). With a hosts-file redirect, clients open a *direct* TLS connection to `127.0.0.1:443` with no `CONNECT`. The `ignore_hosts` regex is parsed against a CONNECT line that never arrives. Strict mode is likely already broken on real machines today.
5. **Uninstall edge cases** — if uninstall doesn't reverse the hosts file edit, `api.anthropic.com` stays pointed at localhost permanently.
6. **Captive portals / VPNs** — outbound TLS termination + re-origination may be blocked even when direct egress is allowed.

Light mode has none of these: it lives entirely in per-app config, is fully reversible by removing one env var, and never touches system DNS or privileged ports.

## Design decisions (from brainstorming Q&A)

| # | Question | Decision |
|---|----------|----------|
| Q1 | Where to register MCP server in MCP-only mode? | Auto-detect installed clients, multi-select prompt with detected clients pre-checked, MCPB bundle remains as Claude Desktop's drag-drop alternative path. |
| Q2 | Proxy invasiveness for "Full" mode? | Drop strict from interactive menu (architecturally fragile; can break system-wide Anthropic). "Full" = light proxy (per-app `ANTHROPIC_BASE_URL`). Strict stays in code as advanced flag, not in interactive menu. |
| Q3 | Depth of interactive flow? | Moderate — 4 prompts: mode, clients, vault dir, embedder backend. Other settings auto. |
| Q4 | Relationship to MCPB bundles? | Independent channels. Install script and MCPB stay separate; verify both still build. |
| Q5a | Backward compat for existing flags? | Aliases with deprecation warnings. `--mode=light` → behaves as `--mode=full`. `--mode=strict` still works, prints "advanced" warning. Removed in 0.10.0. |
| Q5b | Non-interactive flow? | TTY-detect: interactive when `sys.stdin.isatty()`, non-interactive when piped. All settings have flag equivalents (`--vault-dir`, `--embedder`, `--clients`, `--yes`). |

### User-visible modes

Two top-level modes in the interactive menu:

- **Full** — light proxy on `:8443` + MCP tools + RAG/extraction + user-level auto-restart service.
- **MCP-only** — MCP tools + RAG/extraction. No proxy, no `ANTHROPIC_BASE_URL`, no auto-restart service.

Hidden / deprecated modes (still work via flag, not in interactive menu):

- `--mode=strict` — system-wide proxy. Prints "advanced" warning. Requires admin. Not removed.
- `--mode=light` — deprecated alias for `--mode=full`. Prints deprecation warning. Removed in 0.10.0.

## Architecture

```
   piighost install (TTY)         piighost install --mode=full ...
            │                                  │
            ▼                                  ▼
    interactive.py                       flags.py
    (rich prompts)                  (validates flag combo)
            │                                  │
            └────────► InstallPlan ◄──────────┘
                            │
                            ▼
                       executor.py
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
          modes.py     clients.py    service/user_service.py
```

### Module layout (under `src/piighost/install/`)

| File | Status | Purpose |
|------|--------|---------|
| `plan.py` | new | `InstallPlan` dataclass + `Mode`/`Embedder`/`Client` StrEnums |
| `interactive.py` | new | Rich-driven prompts; produces an `InstallPlan` |
| `flags.py` | new | Parses CLI flags; produces an `InstallPlan` |
| `executor.py` | new | Walks the plan, runs each step, prints progress |
| `modes.py` | new | Wraps existing `_run_light_mode` + `_run_strict_mode`; adds `run_mcp_only` (no-op) |
| `clients.py` | new | `detect_all()`, `register()`, `unregister()` for Claude Code + Desktop |
| `recovery.py` | new | `connect()` / `disconnect()` impls |
| `service/user_service.py` | new | Per-platform user-level auto-restart (no admin) |
| `__init__.py` | rewritten | Slim orchestrator + the `run` typer command |
| `ca.py`, `claude_config.py`, `host_config.py`, `docker.py`, `models.py`, `preflight.py`, `trust_store/`, `service/{darwin,linux,windows}.py`, `ui.py`, `uv_path.py`, `hosts_file.py` | preserved | No changes |

The legacy "preflight + docker + uv" branch in `__init__.py` (only reachable via undocumented mode strings) is deleted. The `test_install_fails_gracefully_on_preflight_error` test re-targeted earlier to `--mode=legacy` is updated to assert the new flag-validation error path.

## `InstallPlan` shape

```python
class Mode(StrEnum):
    FULL     = "full"       # light proxy + MCP + RAG (interactive default)
    MCP_ONLY = "mcp-only"   # MCP + RAG, no proxy
    STRICT   = "strict"     # legacy: system-wide proxy (not in menu)

# `--mode=light` is NOT a Mode value. It is mapped to Mode.FULL by
# `flags.py` after printing a deprecation warning, so the executor never
# sees a "light" branch. Keeps the runtime enum minimal.

class Embedder(StrEnum):
    LOCAL   = "local"       # ~500 MB sentence-transformers download
    MISTRAL = "mistral"     # remote API, needs MISTRAL_API_KEY
    NONE    = "none"        # skip RAG embedding

class Client(StrEnum):
    CLAUDE_CODE    = "code"
    CLAUDE_DESKTOP = "desktop"

@dataclass(frozen=True)
class InstallPlan:
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
        if self.embedder == Embedder.MISTRAL and not self.mistral_api_key:
            raise ValueError("Mistral embedder requires mistral_api_key")
        if self.mode == Mode.MCP_ONLY and self.install_user_service:
            raise ValueError("user-service makes no sense in mcp-only mode")
        if self.mode == Mode.STRICT and not self.install_user_service:
            raise ValueError("strict mode needs the auto-restart service")

    def describe(self) -> str:
        """Bullet-list rendering for --dry-run and the closing summary."""
        ...
```

### `executor.execute(plan)` shape

```python
def execute(plan: InstallPlan) -> None:
    if plan.dry_run:
        print(plan.describe())
        return

    _ensure_dirs(plan)                          # vault dir, ~/.piighost/proxy

    if plan.mode == Mode.FULL:
        modes.run_light_mode_proxy(plan)        # CA + leaf cert
    elif plan.mode == Mode.STRICT:
        modes.run_strict_mode_proxy(plan)       # CA + hosts file + sudo service

    for client in plan.clients:
        clients.register(plan, client)          # writes settings/config json

    if plan.install_user_service and plan.mode != Mode.MCP_ONLY:
        user_service.install(plan)              # launchd/systemd-user/schtasks

    if plan.warmup_models:
        models.warmup(plan)                     # download weights

    print_next_steps(plan)
```

## Producers

### Interactive flow (`interactive.py`)

Triggered when `sys.stdin.isatty()` is true and no explicit flags were passed.

```
┌─ piighost install ───────────────────────────────────────────────┐
│                                                                  │
│ 1. Mode                                                          │
│    ▸ Full           Anonymizing proxy + MCP tools + RAG          │
│      MCP-only       MCP tools + RAG. No proxy.                   │
│                                                                  │
│ 2. Register MCP server in: (auto-detected ✓)                     │
│    [✓] Claude Code     (~/.claude/settings.json found)           │
│    [✓] Claude Desktop  (claude_desktop_config.json found)        │
│    Space toggles, Enter confirms.                                │
│                                                                  │
│ 3. Vault directory  [/Users/you/.piighost/vault] ▸               │
│                                                                  │
│ 4. Embedder backend                                              │
│    ▸ Local      ~500 MB download, runs offline                   │
│      Mistral    Remote API, needs MISTRAL_API_KEY                │
│      None       Skip RAG embedding (anonymize-only)              │
│                                                                  │
│ Review:                                                          │
│   • Generate CA + leaf cert at ~/.piighost/proxy/                │
│   • Register MCP in Claude Code, Claude Desktop                  │
│   • Set ANTHROPIC_BASE_URL=https://localhost:8443                │
│   • Install user-level auto-restart service                      │
│   • Vault: /Users/you/.piighost/vault                            │
│   • Embedder: local (downloading 500 MB)                         │
│                                                                  │
│ Proceed? [Y/n]                                                   │
└──────────────────────────────────────────────────────────────────┘
```

Edge cases:
- Mistral picked, no API key → prompt for `MISTRAL_API_KEY`.
- No Claude clients detected → present multi-select with both unchecked.
- `embedder=NONE` → review hides the embedder line; closing message warns "RAG indexing/query disabled until you set an embedder via `piighost config set embedder ...`".

### Non-interactive flow (`flags.py`)

```
piighost install \
  --mode={full|mcp-only|strict|light} \
  --vault-dir=/path/to/vault \
  --embedder={local|mistral|none} \
  --mistral-api-key=$KEY \
  --clients=code,desktop \
  --no-user-service \
  --warmup \
  --force \
  --dry-run \
  --yes
```

Defaults (so `curl | bash --mode=full` works):

| Flag | Default |
|------|---------|
| `--vault-dir` | `~/.piighost/vault` |
| `--embedder` | `local` |
| `--clients` | auto-detected (same logic as interactive) |
| `--user-service` | true (false if mode is mcp-only) |
| `--warmup` | false (lazy on first use) |
| `--yes` | required when stdin not a TTY; in TTY mode it skips the final review |

Validation rules raise `typer.BadParameter`:
- `--embedder=mistral` requires `--mistral-api-key` or `MISTRAL_API_KEY` env.
- `--mode=strict` is incompatible with `--no-user-service`.
- `--mode=mcp-only` is incompatible with `--user-service` (warned, not errored).
- `--mode=light` prints deprecation warning, sets `mode=Mode.FULL` internally.
- Unknown client name in `--clients` → error listing valid options.

### TTY detection

```python
def _should_prompt(args) -> bool:
    if args.yes: return False
    if args.dry_run: return False
    if not sys.stdin.isatty(): return False
    if any(_explicit_flag_set(args, f) for f in EXPLICIT_FLAGS):
        return False  # caller passed enough flags; assume scripted
    return True
```

## Mode runners + client registration

### `modes.py`

Three runners, all idempotent:

```python
def run_light_mode_proxy(plan: InstallPlan) -> None:
    """Generate CA + leaf cert at <vault>/proxy/. No system changes."""
    # Existing _run_light_mode logic minus the host_config write
    # (client registration moved to clients.py).

def run_strict_mode_proxy(plan: InstallPlan) -> None:
    """CA + leaf for api.anthropic.com + hosts file + sudo service.
    Reachable only via --mode=strict (deprecated, warned)."""
    # Existing _run_strict_mode logic.

def run_mcp_only(plan: InstallPlan) -> None:
    """No-op. RAG/extraction work is provided by piighost[mcp,index,gliner2]
    extras at install time; this runner exists only as a symmetry point."""
    pass
```

### `clients.py`

```python
@dataclass(frozen=True)
class ClientLocation:
    client: Client
    config_path: Path
    exists: bool

def detect_all() -> list[ClientLocation]: ...
def register(plan: InstallPlan, client: Client) -> None: ...
def unregister(client: Client, *, remove_base_url: bool, remove_mcp: bool) -> None: ...
```

| Client | Config path | MCP entry goes in | BASE_URL goes in |
|--------|------------|-------------------|------------------|
| Claude Code | `~/.claude/settings.json` | `mcpServers.piighost` | `env.ANTHROPIC_BASE_URL` |
| Claude Desktop | macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`<br>Windows: `%APPDATA%\Claude\claude_desktop_config.json`<br>Linux: `~/.config/Claude/claude_desktop_config.json` | `mcpServers.piighost` | (skipped — Desktop doesn't honor env there) |

MCP entry format:

```json
{
  "command": "uvx",
  "args": ["--from", "piighost[mcp,index,gliner2,cache]",
           "piighost", "serve", "--transport", "stdio"],
  "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
          "PIIGHOST_VAULT_DIR": "<plan.vault_dir>"}
}
```

Backup: every config file gets a `.piighost.bak` next to it before first modification (only if no `.bak` already exists, so re-runs don't lose pre-piighost state).

Conflict handling: if `mcpServers.piighost` already points at a different command, surface a diff and require `--force` to overwrite — same pattern as existing `claude_config.merge_mcp_entry`.

### Honest gap re. Claude Desktop + proxy

When `mode=FULL` and the user picks Claude Desktop:

- ✅ MCP server is registered in Desktop config (RAG/extraction tools available).
- ⚠️ Desktop's outbound `api.anthropic.com` calls are **not** anonymized by the light proxy — those go direct.
- ✅ Claude Code calls **are** anonymized (BASE_URL env var works there).

The closing summary flags this honestly: *"Claude Desktop will use piighost MCP tools but its API calls bypass the anonymizing proxy. For full Desktop coverage, install the `piighost-full.mcpb` bundle, or use `--mode=strict` (system-wide intercept, requires admin)."*

## Recovery + auto-restart

### `recovery.py`

```python
def connect(clients: frozenset[Client] | None = None) -> None:
    """Re-add ANTHROPIC_BASE_URL to the named clients (default: detected)."""

def disconnect(clients: frozenset[Client] | None = None) -> None:
    """Remove ANTHROPIC_BASE_URL from the named clients. MCP server
    registration is preserved — disconnecting only stops *proxy*
    interception, leaves the tools available."""
```

Both commands rewrite the JSON statelessly. They work whether the proxy is up, down, or completely uninstalled.

CLI surface:

```
piighost connect                    # default: all detected clients
piighost connect --client=code      # specific client
piighost disconnect                 # remove BASE_URL everywhere
piighost disconnect --client=code   # specific client
```

### Extended `doctor`

Existing `piighost doctor` gains a "proxy reachability" check:

```
$ piighost doctor

[OK]   piighost binary on PATH
[OK]   ~/.piighost/proxy/ca.pem present
[OK]   ~/.piighost/proxy/leaf.pem valid (expires 2027-04-26)
[FAIL] proxy listening on https://localhost:8443
       ANTHROPIC_BASE_URL is set in ~/.claude/settings.json,
       but :8443 is unreachable. Anthropic API calls from
       Claude Code will fail until the proxy is restarted
       OR the BASE_URL is removed.

       Fix options:
         1. Start the proxy:    piighost serve &
         2. Disconnect:         piighost disconnect
         3. Reinstall service:  piighost install --user-service
```

Exit codes: 0 = all OK, 1 = warnings, 2 = at least one FAIL.

### `service/user_service.py` — unprivileged auto-restart

Three platform implementations. **None require admin/sudo.**

| Platform | Mechanism | Path |
|----------|-----------|------|
| macOS | LaunchAgent (User Agent, runs as user UID at login + on demand, restarts on crash) | `~/Library/LaunchAgents/com.piighost.proxy.plist` |
| Linux | systemd `--user` unit | `~/.config/systemd/user/piighost-proxy.service` (runs `loginctl enable-linger $USER` once if not enabled, so it survives logout) |
| Windows | Scheduled Task with `/onlogon` trigger, current user only | `\piighost\proxy` via `schtasks.exe /create /sc onlogon /rl limited` |

```python
@dataclass(frozen=True)
class UserServiceSpec:
    name: str           # "com.piighost.proxy"
    bin_path: Path      # absolute path to `piighost` binary
    vault_dir: Path
    log_dir: Path       # ~/.piighost/logs/
    listen_port: int    # 8443

def install(spec: UserServiceSpec) -> None: ...
def uninstall(spec: UserServiceSpec) -> None: ...
def status(spec: UserServiceSpec) -> Literal["running", "stopped", "missing"]: ...
def restart(spec: UserServiceSpec) -> None: ...
```

Restart-on-crash policies:
- macOS LaunchAgent: `KeepAlive=true, ThrottleInterval=10` — restarts within 10s on crash.
- systemd `--user`: `Restart=on-failure, RestartSec=5s`.
- Windows Task: `/sc onlogon` only — Windows lacks a clean unprivileged equivalent of LaunchAgent's `KeepAlive`. We document the gap and recommend running `piighost serve` from a terminal in long-lived dev sessions, or using strict mode with admin if uptime is critical.

Coexistence with strict mode: if the user later runs `piighost install --mode=strict`, the user-level service is uninstalled before the system-level one is installed.

### Closing summary at end of install

```
✓ piighost installed in Full mode.

Proxy:        https://localhost:8443  (auto-restarts at login)
Vault:        /Users/you/.piighost/vault
Embedder:     local
Anonymizing:  Claude Code
MCP tools:    Claude Code, Claude Desktop

Useful commands:
  piighost status          - is the proxy running?
  piighost on / off        - toggle anonymization (proxy stays up)
  piighost connect / disconnect
                           - add/remove ANTHROPIC_BASE_URL from client config
  piighost doctor          - diagnose & self-heal
  piighost uninstall       - clean removal

Last-resort recovery (if 'piighost' itself is broken):
  Edit ~/.claude/settings.json and remove env.ANTHROPIC_BASE_URL.
```

## Testing

| Layer | Test file | Strategy |
|-------|-----------|----------|
| `plan.py` | `tests/install/test_plan.py` | Pure dataclass: validate `__post_init__` raises on bad combos; `describe()` output snapshots |
| `flags.py` | `tests/install/test_flags.py` | Typer CliRunner; assert produced `InstallPlan` equals expected; deprecation warning on `--mode=light` is captured |
| `interactive.py` | `tests/install/test_interactive.py` | rich's `Console.input` is mocked; feed scripted answers; assert resulting `InstallPlan` |
| `executor.py` | `tests/install/test_executor.py` | Inject fake `modes`/`clients`/`user_service` modules via monkeypatch; assert each step is or isn't called per the plan; dry-run path prints plan and skips execution |
| `clients.py` | `tests/install/test_clients.py` | tmp_path-isolated HOME; write fixtures into fake config dirs; assert idempotent writes, backup creation, conflict detection |
| `recovery.py` | `tests/install/test_recovery.py` | connect/disconnect on tmp settings.json; assert MCP entry untouched while BASE_URL is added/removed |
| `service/user_service.py` | `tests/install/test_user_service_*.py` | One file per platform (`darwin`/`linux`/`windows`), gated with `pytest.mark.skipif(sys.platform != ...)`; subprocess calls mocked, assert correct args to `launchctl` / `systemctl --user` / `schtasks.exe` |
| End-to-end | `tests/install/test_install_e2e.py` | `runner.invoke(app, ["install", "--mode=mcp-only", "--vault-dir=...", ..., "--yes"])` with `PIIGHOST_SKIP_TRUSTSTORE/SERVICE/USERSVC` env vars; verify `settings.json` + `claude_desktop_config.json` end up correct |

The 5 install_cmd tests fixed earlier in this session stay — they shift from "test the install command" to "test the legacy mode dispatch + the deprecation alias". One new test covers `--mode=light` printing a deprecation warning and behaving as `--mode=full`.

## Migration

| Surface | Action |
|---------|--------|
| `scripts/install.sh` | Default `MODE=full` (was `strict`). Default `EXTRAS=proxy,mcp,index,gliner2,cache` (unchanged — `proxy` is needed for `--mode=full`; `mcp-only` users get a few extra MB of unused mitmproxy deps, acceptable bloat for a simpler bash script). Honor existing `PIIGHOST_MODE=strict` for users who explicitly set it. |
| `scripts/install.ps1` | Same updates. |
| `piighost install --mode=light` | Prints `[deprecated] --mode=light is now '--mode=full'. This alias will be removed in 0.10.0.` and proceeds as full. |
| `piighost install --mode=strict` | Prints `[advanced] strict mode requires admin and modifies your hosts file. Most users want '--mode=full' instead. See docs/install.md.` and proceeds. Not removed. |
| `--no-docker`, `--reranker`, `--full` (the old `--full` model-warmup flag) | Deprecated. `--full` (warmup) becomes `--warmup` for clarity (the word "full" now refers to the mode). One release of warning, then removed. |
| `MCP_ENTRY_UV` constant in `install/__init__.py` | Moves to `install/clients.py` as `_mcp_entry(plan)` (function so vault dir + extras can vary by plan). |

## MCPB sanity

No code changes to `bundles/{core,full}/` or `scripts/build_mcpb.py`. CI verifies:

- `python scripts/build_mcpb.py` still produces `dist/mcpb/piighost-{core,full}.mcpb`.
- The two bundles' `manifest.json` versions match `pyproject.toml` version.
- Smoke test: extract each `.mcpb`, check `manifest.json` is valid JSON and `pyproject.toml` lists `piighost[<extras>]==<version>`.

A new CI check `scripts/check_mcpb_consistency.py` runs after every `pyproject.toml` version bump and asserts the bundle versions match.

A new doc page `docs/install-paths.md` compares the two channels:

```
                            install script        MCPB bundle
                            ──────────────        ───────────
Audience                    has terminal          GUI-only
Bootstrap                   curl | bash           drag .mcpb onto Desktop
Anonymizing proxy           full mode includes    not available
                            (mcp-only skips)
Auto-restart on login       yes                   N/A (Desktop manages)
Vault dir                   user-chosen           ~/.piighost/vault
MCP server                  registered in your    isolated to Desktop
                            chosen client(s)      extension sandbox
```

## Out of scope

- Reranker model selection (kept as `~/.piighost/config.toml` post-install setting).
- Detector backend choice (gliner2 stays the default; `regex_only` reachable via config file).
- Telemetry / audit log retention policy.
- The `piighost config` command surface (referenced as the place to retune deferred settings, but its implementation is its own spec).
- Generic "ansible-style" plan replay / export (the `InstallPlan` dataclass is structured to support this later but no replay machinery is built now).
- Fixing strict mode's architectural issues (the mitmproxy `regular` vs `transparent` mismatch). Strict stays as-is, deprecated for users, with a doc note that it may not work reliably with hosts-file redirect.

## Risks

| Risk | Mitigation |
|------|-----------|
| User runs `--mode=light` after upgrade and is confused by the deprecation message | Message includes the exact replacement flag; behavior is unchanged |
| User's `~/.claude/settings.json` already contains a `piighost` MCP entry from an earlier install | Conflict detection in `clients.register`; `--force` overwrites, otherwise diff-and-abort |
| User-level service fails to start on first login | `piighost doctor` covers this; closing summary shows the `piighost serve &` manual fallback |
| Mistral API key is captured in a shell history when passed via `--mistral-api-key=$KEY` | Document that `MISTRAL_API_KEY` env var is preferred; flag exists for completeness |
| Windows user-service has no equivalent of `KeepAlive` | Documented limitation; user can fall back to running `piighost serve` from a terminal |
| Strict mode is preserved as a flag but is architecturally fragile | Out-of-scope to fix; `[advanced]` warning makes the risk explicit at install time |

## Filesystem layout clarification

The plan distinguishes two roots, which matter for tests, encrypted-disk users, and uninstall:

| Path | Configurable? | Holds |
|------|---------------|-------|
| `vault_dir` (default `~/.piighost/vault`) | yes — user-prompted in interactive flow | PII vault DB, indexed-document store, audit logs, project registry. The thing a privacy-conscious user might want on an encrypted disk. |
| `~/.piighost/proxy/` | no — always there | CA cert + key, leaf cert, mitmproxy signing CA copy. Not sensitive data; never moved. |
| `~/.piighost/logs/` | no — always there | Daemon stdout/stderr from the user-level service. |
| `~/.piighost/daemon.json` | no — always there | Singleton daemon handshake (port + token + pid). Runtime artifact. |

The MCP entry's `PIIGHOST_VAULT_DIR` env var passes the user's `vault_dir` choice to the server. The CA path is derived from `Path.home() / ".piighost" / "proxy"` and not influenced by the vault choice. This matches the existing MCPB bundle convention (`user_config.vault_dir.default = "${HOME}/.piighost/vault"`).

## Open questions

None — all five Q&A rounds resolved.
