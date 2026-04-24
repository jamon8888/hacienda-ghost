# Phase 1 E2E Verification Results

**Date:** 2026-04-24
**OS:** Windows 10 Pro (10.0.19045)
**Python:** 3.13.2
**Tool:** uv / piighost 0.7.0

---

## Step 1: Full test suite

Command: `python -m pytest tests/proxy tests/install tests/cli/test_proxy_cmd.py tests/cli/test_doctor.py -v --tb=short`

**Result: PASS**

- 47 passed, 4 skipped (macOS and Linux trust-store tests skipped on Windows — expected)
- 0 failures, 0 errors
- Runtime: 11.73s

Note: `uv run pytest ...` failed with an access-denied error trying to overwrite `piighost.exe` (locked by the shell). Workaround: ran pytest directly via the venv Python, which bypasses the reinstall step. This is a Windows-specific `uv` packaging quirk, not a code defect.

---

## Step 2: Install in light mode

Command: `PIIGHOST_SKIP_TRUSTSTORE=1 PYTHONUTF8=1 .venv/Scripts/piighost.exe install --mode=light`

**Result: PASS (exit 0)**

Output:
```
→ Generating local root CA and leaf certificate
✓ CA and leaf cert written to ~/.piighost/proxy/

→ Installing CA into OS trust store
  PIIGHOST_SKIP_TRUSTSTORE=1 — skipping trust store installation.

→ Configuring Claude Code (ANTHROPIC_BASE_URL)
✓ ANTHROPIC_BASE_URL written to C:\Users\NMarchitecte\.claude\settings.json
✓
Light mode installed. Start the proxy with: piighost proxy run
```

Note: `PYTHONUTF8=1` was required to prevent a `UnicodeEncodeError` from Rich's legacy Windows console renderer trying to encode the `→` (U+2192) character in cp1252. Without it, the install crashes before doing any work. This is a bug that needs fixing (see issues section below).

---

## Step 3: Files created

| File | Status | Size |
|------|--------|------|
| `~/.piighost/proxy/ca.pem` | EXISTS | 1074 bytes |
| `~/.piighost/proxy/leaf.pem` | EXISTS | 1070 bytes |
| `~/.claude/settings.json` | EXISTS — `ANTHROPIC_BASE_URL: https://localhost:8443` present | — |

All three artifacts confirmed.

---

## Step 4: Doctor output

Command: `PYTHONUTF8=1 .venv/Scripts/piighost.exe doctor`

**Result: PASS (expected exit 1)**

Output:
```
Checking proxy handshake…
Checking Claude Code settings.json…
  ok: https://localhost:8443
Checking CA cert on disk…
  ok

FAILURES:
  x proxy: no handshake file (not running)
EXIT_CODE: 1
```

Doctor correctly reports the proxy is not running (no handshake file). The settings.json and CA cert checks passed. Behavior is correct — proxy was not started.

---

## Issues Found

### Bug: Windows cp1252 encoding crash in `ui.py`

**Severity:** High — blocks `piighost install` on Windows without workaround

**Root cause:** `src/piighost/install/ui.py` uses Unicode characters (`→` U+2192, `✓` U+2713, `⚠` U+26A0, `✗` U+2717) in Rich console output. On Windows with the legacy console renderer and cp1252 encoding, these characters cannot be encoded and raise `UnicodeEncodeError`.

**Workaround used:** `PYTHONUTF8=1` env var (Python 3.7+ UTF-8 mode).

**Recommended fix:** Either:
1. Add `PYTHONUTF8=1` to the launcher script / docs, OR
2. Replace the Unicode symbols with ASCII fallbacks (`->`, `OK`, `!`, `X`) or use Rich's `safe_box` / `markup` alternatives that degrade gracefully, OR
3. Instantiate the Rich `Console` with `force_terminal=False` or `highlight=False` in non-interactive mode.

### Minor: `uv run` locks piighost.exe on Windows

`uv run piighost ...` fails with "Access denied" when trying to reinstall `piighost.exe` if the file is already in use by the current shell session. Not a code bug — use `uv run python -c "..."` or the venv exe directly as a workaround on Windows.

---

## Summary

Phase 1 install flow works correctly on Windows 10. The core functionality (CA generation, settings injection, doctor diagnostics) is fully functional. One blocker exists for out-of-the-box use: the Unicode encoding crash requires `PYTHONUTF8=1` to be set, which is not documented and not set automatically by the installer. This should be fixed before the Windows release.
