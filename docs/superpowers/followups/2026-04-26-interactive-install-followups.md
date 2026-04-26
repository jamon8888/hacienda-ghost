# Interactive Install Redesign — Follow-up Issues

**Date:** 2026-04-26
**Source:** Final code review of `feat/interactive-install` (commits `9323ffd..1b66c14`)
**Spec:** [docs/superpowers/specs/2026-04-26-interactive-install-redesign.md](../specs/2026-04-26-interactive-install-redesign.md)
**Plan:** [docs/superpowers/plans/2026-04-26-interactive-install-redesign.md](../plans/2026-04-26-interactive-install-redesign.md)

This file collects issues found during the final code review that were deliberately **not** fixed before merge. Each entry has enough context that a future engineer (or a future you) can pick it up cold.

Severity legend:

- 🟡 **IMPORTANT** — should be addressed in a follow-up PR within a release or two
- 🟢 **NICE-TO-HAVE** — track loosely; close if priorities shift

---

## 🟡 1. Dead `--mode=light` branch in `flags._resolve_mode`

**File:** `src/piighost/install/flags.py:97-110`

Task 12 introduced a backward-compat short-circuit in `install/__init__.py:run()` that handles `--mode=light` and `--mode=strict` directly (calls the legacy `_run_light_mode` / `_run_strict_mode` helpers and returns) before ever reaching `flags.parse_flags()`. As a result, the `if raw == "light"` branch in `flags._resolve_mode()` is unreachable from the CLI install path today.

It is still reachable from non-CLI Python callers that import `parse_flags` directly (none in this repo, but external code could). Two options:

- **Option A (simpler):** Delete the short-circuit in `__init__.py:run()` and route all modes through the executor. Update the pre-existing tests at `tests/install/test_install_light_mode.py` and `tests/install/test_install_strict_mode.py` to assert the new code path. This unifies the deprecation message in one place (`flags.DeprecationNotice`) and makes the architecture diagram in the spec match reality.
- **Option B:** Delete just the dead `flags._resolve_mode("light")` branch and accept the duplication.

Option A is preferred — the duplication will rot. Estimated effort: ~1 hour including test updates.

---

## 🟡 2. Mistral API key echoes in interactive prompt

**File:** `src/piighost/install/interactive.py:106-110`

The interactive prompt for `MISTRAL_API_KEY` uses `_ask` which is a thin wrapper over `input()`, so the key is visible on screen and may be captured by terminal scrollback / screen recorders.

The fix is to introduce a separate `_ask_secret` indirection backed by `getpass.getpass()` in production, with a separate test hook. Tests currently inject a scripted iterator into `_ask`; if `_ask_secret` calls `_ask` internally the security improvement is illusory, but if it calls `getpass.getpass` directly the existing `test_mistral_prompts_for_key` test breaks.

Suggested approach:

```python
# At module level
_secret_input = getpass.getpass  # tests can monkeypatch this

def _ask_secret(prompt: str) -> str:
    return _secret_input(prompt + " ").strip()
```

Then update `test_interactive.py::test_mistral_prompts_for_key` to monkeypatch `_secret_input` separately:

```python
monkeypatch.setattr("piighost.install.interactive._ask", _scripted(["1", "1", "", "2", "y"]))
monkeypatch.setattr("piighost.install.interactive._secret_input", lambda _: "sk-test")
```

Also: the typer flag `--mistral-api-key` in `install/__init__.py` should explicitly note in its help text "prefer `MISTRAL_API_KEY` env var to avoid shell history capture." Right now the docstring is silent.

---

## 🟡 3. Windows schtasks `/tr` quoting may break on `C:\Program Files\…`

**File:** `src/piighost/install/service/_user_service_windows.py:29-31`

```python
cmd = f'"{spec.bin_path}" serve --listen-port {spec.listen_port}'
```

`schtasks /tr` has a 261-character limit and gets confused by nested quoting. If `bin_path` is something like `C:\Program Files\piighost\piighost.exe` the call may silently fail.

The robust fix is to write a stub `.cmd` wrapper into `~/.piighost/run-proxy.cmd` and point the scheduled task at that file (no quoting issues, no length limit, easier to inspect/debug):

```cmd
@echo off
"%LOCALAPPDATA%\piighost\piighost.exe" serve --listen-port 8443
```

Then `cmd = str(home / ".piighost" / "run-proxy.cmd")` — a single quoted argument with no length issues.

---

## 🟡 4. macOS uses legacy `launchctl load` instead of `bootstrap`

**File:** `src/piighost/install/service/_user_service_darwin.py:40, 42`

`launchctl load -w <plist>` is the pre-10.10 API. The modern equivalent is `launchctl bootstrap gui/<uid> <plist>`. Legacy still works through macOS Sequoia (15.x) but emits deprecation warnings to syslog.

Migration:

```python
import os
uid = os.getuid()
subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], check=True)
# uninstall:
subprocess.run(["launchctl", "bootout", f"gui/{uid}/{spec.name}"], check=False)
```

Test fixtures in `tests/install/test_user_service_darwin.py` will need updating to assert the new arg shape.

---

## 🟢 5. Strict mode is architecturally fragile

**Files:** `src/piighost/install/__init__.py:_run_strict_mode`, `src/piighost/proxy/forward/__main__.py:91-101`

Pre-existing issue, out of scope for this redesign. Strict mode launches mitmproxy in `mode=["regular"]` (explicit forward proxy expecting a `CONNECT api.anthropic.com:443 HTTP/1.1` line from the client), but combines it with a hosts-file redirect that makes clients open a *direct* TLS connection to `127.0.0.1:443` — no `CONNECT` ever arrives. The `ignore_hosts` regex in `forward/__main__.py:99` is matched against the missing CONNECT line.

This was flagged in the redesign spec as a known issue. Fixing properly requires either:

- Switch to `mode=["transparent"]` plus iptables/pf rules (per-OS plumbing).
- Or remove `--mode=strict` entirely in 0.10.0 and document MCPB as the no-CLI alternative.

Track this as a separate spec/plan when prioritized.

---

## 🟢 6. No telemetry on which mode users pick

**File:** `src/piighost/install/executor.py`

Useful signal for deciding whether to delete strict mode (item 5) or invest in fixing it. A single anonymous counter ping with the chosen mode + OS at install time would be enough. Out of scope unless we add opt-in telemetry plumbing more broadly.

---

## 🟢 7. `piighost config set embedder ...` is referenced but doesn't exist

**Files:**
- `src/piighost/install/plan.py:88-91` (in `describe()` for `Embedder.NONE`)
- `src/piighost/install/executor.py:_print_next_steps` (closing summary)

Both places suggest running `piighost config set embedder ...` to retune deferred settings. That command doesn't exist yet. Two options:

- Ship a minimal `piighost config` typer subcommand that reads/writes `~/.piighost/config.toml`. Spec called this out as out of scope but the messages already promise it.
- Or replace those references with `piighost install --embedder=...` (re-running install with a flag).

The second is shorter; the first is more discoverable.

---

## 🟢 8. `scripts/install.sh` always passes `--mode="$MODE"`

**File:** `scripts/install.sh:64`

```bash
piighost install --mode="$MODE"
```

`MODE` defaults to `full`, which is also the install command's default. So the script always passes a redundant `--mode=full`. Cosmetic, but makes the user-facing invocation slightly noisier. Either:

- Only pass `--mode` when `MODE != "full"`:
  ```bash
  if [ "$MODE" != "full" ]; then
      piighost install --mode="$MODE"
  else
      piighost install
  fi
  ```
- Or accept the noise.

Same applies to `scripts/install.ps1`.

---

## 🟢 9. No e2e test for stdin-not-a-TTY path

**File:** `src/piighost/install/__init__.py:_should_prompt`

Logic is unit-tested via `flags.py`'s test suite, but no e2e test asserts that piping into `piighost install` (closed stdin) gracefully refuses to prompt. A 5-line addition to `tests/install/test_install_e2e.py`:

```python
def test_install_refuses_when_stdin_closed_and_no_yes(isolated_install_env, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    result = runner.invoke(app, ["install"])
    # expect either a clear error or a fall-through to defaults
    assert result.exit_code != 0 or "DRY RUN" in result.output
```

The exact assertion depends on the desired UX (fail loudly vs silently use defaults). Worth a quick design call.

---

## 🟢 10. macOS `claude_desktop_config.json` writes don't backup-rotate

**File:** `src/piighost/install/clients.py:_write_backup`

Backup is taken once on the first `register()` call. Re-registering with `--force` overwrites without taking a fresh backup. If a user manually edits the config between two `piighost install --force` invocations, the manual edit is silently lost.

Mitigations:

- Document in `docs/install-paths.md` ("re-running `--force` does not snapshot manual edits").
- Or implement `.piighost.bak.N` rotation (keep last 3 backups).

Documentation is probably enough; rotation adds disk churn for no clear win.

---

## 🟢 11. `register()` conflict diff is class-name-only

**File:** `src/piighost/install/clients.py:97-99`

```python
raise RuntimeError(
    f"conflict: mcpServers.piighost in {location.config_path} differs "
    f"from desired entry. Re-run with --force to overwrite."
)
```

The error tells the user there's a conflict but not what differs. A two-line improvement:

```python
import difflib
diff = "\n".join(difflib.unified_diff(
    json.dumps(existing, indent=2).splitlines(),
    json.dumps(desired_entry, indent=2).splitlines(),
    fromfile="existing", tofile="desired", lineterm="",
))
raise RuntimeError(
    f"conflict: mcpServers.piighost in {location.config_path} differs "
    f"from desired entry:\n{diff}\nRe-run with --force to overwrite."
)
```

Worth doing if users hit the conflict path even occasionally.

---

## 🟢 12. Sorting `frozenset[Client]` relies on enum value strings

**File:** `src/piighost/install/executor.py:40`

```python
for client in sorted(plan.clients):
```

Works because `Client` is a `StrEnum` (sorts by underlying string value `"code"` < `"desktop"`). Fine in practice, but the sort key is implicit. Make it explicit so a future rename of enum values (`"code"` → `"claude-code"`) doesn't silently swap the iteration order:

```python
for client in sorted(plan.clients, key=lambda c: c.value):
```

Or define a canonical order at the `Client` level.

---

## 🟢 13. `install_user_service` default is duplicated across producers

**Files:**
- `src/piighost/install/flags.py:71-75`
- `src/piighost/install/interactive.py:33` (line numbers approximate)

Both producers infer the default for `install_user_service` from the chosen `mode`:

```python
install_user_service = mode is not Mode.MCP_ONLY  # interactive
resolved_user_service = resolved_mode is not Mode.MCP_ONLY  # flags
```

Move the rule into `InstallPlan` itself:

```python
@classmethod
def default_user_service_for(cls, mode: Mode) -> bool:
    return mode is not Mode.MCP_ONLY
```

Then both producers call `InstallPlan.default_user_service_for(mode)`. Single source of truth.

---

## How to handle this list

These are not blockers. The recommendation is:

1. File items 1–4 (🟡) as separate GitHub issues with this doc as the source link.
2. Group items 5–13 (🟢) into a single "post-install-redesign polish" milestone.
3. Re-evaluate items 5 and 6 together — if telemetry shows nobody picks `--mode=strict`, just delete it.

Close items as they're addressed. If something stays open for more than two minor releases, decide whether it's actually wanted or should be dropped from the list.
