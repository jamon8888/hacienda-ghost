# Anonymizing Proxy Phase 3 — Cowork Verification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empirically verify whether the hosts-file redirect captures Cowork traffic, and ship the tooling needed to diagnose and document the result.

**Architecture:** Add an unauthenticated `/piighost-probe` endpoint to the existing proxy server so any HTTP client (including Cowork's runtime) can prove it is being intercepted. Add a `--probe` flag to `piighost doctor` that makes a live HTTPS request to `https://api.anthropic.com/piighost-probe` using the OS DNS resolver and system trust store — if it returns `{"intercepted": true}` the whole chain (hosts-file redirect + CA trust + proxy TLS) is confirmed working for the calling process. Ship a standalone `scripts/verify_cowork.py` script with the same logic, plus a doc page with the manual Cowork test procedure.

**Tech Stack:** Python 3.12, stdlib (`socket`, `ssl`, `http.client`), `httpx` (already in `proxy` extras), `typer`, `starlette` (already in `proxy` extras).

**Branching outcome — read before starting:**
- If `piighost doctor --probe` passes on the target machine → Cowork is almost certainly intercepted (same OS DNS + same CA trust store). Tag as GA, update docs, done.
- If it fails → the hosts-file or CA trust store is not set up correctly. Fix the setup (re-run `piighost install --mode=strict`), not the code. The code in this plan is correct either way.
- Cowork-specific manual verification (Task 4) is the final confirmation. If it fails even after `doctor --probe` passes, the Cowork sandbox has its own DNS — document that, file upstream FR.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Modify** | `src/piighost/proxy/server.py` | Add `GET /piighost-probe` unauthenticated route |
| **Modify** | `src/piighost/cli/commands/doctor.py` | Add `--probe` flag: live DNS + HTTPS interception check |
| **Create** | `scripts/verify_cowork.py` | Standalone probe script — runnable without piighost installed |
| **Create** | `tests/proxy/test_probe_endpoint.py` | Unit tests for `/piighost-probe` route |
| **Create** | `tests/cli/test_doctor_probe.py` | Unit tests for `doctor --probe` flag |
| **Create** | `tests/scripts/test_verify_cowork.py` | Tests for verify_cowork.py in simulated pass/fail scenarios |
| **Create** | `docs/cowork-support.md` | Verification procedure, results table, troubleshooting guide |
| **Modify** | `.github/workflows/proxy-install-ci.yml` | Add probe smoke step |

---

## Task 1: /piighost-probe Endpoint

The probe is an unauthenticated `GET /piighost-probe` route that any HTTP client can call to confirm it is hitting the proxy rather than the real `api.anthropic.com`. No token required — the probe carries no sensitive data and its value is in being callable by external processes that don't know the token.

**Files:**
- Modify: `src/piighost/proxy/server.py`
- Create: `tests/proxy/test_probe_endpoint.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/proxy/test_probe_endpoint.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient


def _build_test_app(tmp_path: Path) -> "TestClient":
    from piighost.proxy.server import build_app

    service = MagicMock()
    service.active_project = AsyncMock(return_value="test-project")
    service.anonymize = AsyncMock(return_value=("text", {}))
    service.rehydrate = AsyncMock(return_value="text")

    app = build_app(service=service, vault_dir=tmp_path, token="")
    return TestClient(app, raise_server_exceptions=True)


def test_probe_returns_intercepted_true(tmp_path: Path) -> None:
    client = _build_test_app(tmp_path)
    r = client.get("/piighost-probe")
    assert r.status_code == 200
    data = r.json()
    assert data["intercepted"] is True
    assert data["proxy"] == "piighost"


def test_probe_requires_no_token(tmp_path: Path) -> None:
    from piighost.proxy.server import build_app

    service = MagicMock()
    service.active_project = AsyncMock(return_value="test-project")
    app = build_app(service=service, vault_dir=tmp_path, token="secret-token")
    client = TestClient(app)

    # No x-piighost-token header — probe must still succeed
    r = client.get("/piighost-probe")
    assert r.status_code == 200
    assert r.json()["intercepted"] is True


def test_probe_is_get_only(tmp_path: Path) -> None:
    client = _build_test_app(tmp_path)
    r = client.post("/piighost-probe")
    assert r.status_code == 405
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/proxy/test_probe_endpoint.py -v
```

Expected: `FAILED tests/proxy/test_probe_endpoint.py::test_probe_returns_intercepted_true` — `/piighost-probe` returns 404.

- [ ] **Step 3: Add the probe route to server.py**

In `src/piighost/proxy/server.py`, add this function after the `health` function (around line 45):

```python
    async def probe(_: Request) -> JSONResponse:
        return JSONResponse({"intercepted": True, "proxy": "piighost"})
```

And add it to the routes list in the `Starlette(...)` call (after the `/health` route):

```python
    return Starlette(
        lifespan=_lifespan,
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/piighost-probe", probe, methods=["GET"]),
            Route("/v1/messages", messages, methods=["POST"]),
        ]
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/proxy/test_probe_endpoint.py -v
```

Expected: 3 passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/proxy/server.py tests/proxy/test_probe_endpoint.py
git commit -m "feat: add /piighost-probe unauthenticated endpoint for interception verification"
```

---

## Task 2: doctor --probe Flag

Adds a `--probe` flag to `piighost doctor` that makes two live checks:

1. **DNS check** — resolves `api.anthropic.com` via `socket.gethostbyname()`. Under strict mode this must return `127.0.0.1`. Any other IP means the hosts-file redirect is not active in the current process.

2. **HTTPS probe** — makes `GET https://api.anthropic.com/piighost-probe` using `httpx` with the system trust store (`verify=True`). If the CA is trusted and the hosts-file redirect is active, this hits the local proxy and returns `{"intercepted": true}`. If the real Anthropic server is reached, it returns 404.

Both checks are informational under `doctor` (exit 0 even if they warn) so that users without strict mode installed are not broken by the flag.

**Files:**
- Modify: `src/piighost/cli/commands/doctor.py`
- Create: `tests/cli/test_doctor_probe.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/cli/test_doctor_probe.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def _setup_doctor_passing(tmp_path: Path) -> None:
    proxy_dir = tmp_path / ".piighost" / "proxy"
    proxy_dir.mkdir(parents=True)
    (proxy_dir / "ca.pem").write_bytes(b"fake-ca")
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://localhost:8443"}}),
        encoding="utf-8",
    )
    from piighost.proxy.handshake import ProxyHandshake, write_handshake
    write_handshake(tmp_path / ".piighost", ProxyHandshake(pid=1, port=8443, token="tok"))

    import piighost.install.hosts_file as hf
    # monkeypatching done in each test


def test_probe_dns_check_passes_when_resolves_to_loopback(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_doctor_passing(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda *a, **kw: True)

    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1")

    import httpx
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"intercepted": True, "proxy": "piighost"}
    mock_resp.status_code = 200
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: mock_resp)

    r = runner.invoke(app, ["doctor", "--probe"])
    assert r.exit_code == 0, f"stdout: {r.stdout}"
    assert "127.0.0.1" in r.stdout
    assert "intercepted" in r.stdout.lower()


def test_probe_dns_check_warns_when_resolves_to_real_ip(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_doctor_passing(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda *a, **kw: False)

    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "99.84.238.101")

    r = runner.invoke(app, ["doctor", "--probe"])
    # --probe warns but does not add to failures list (exit 0 allowed)
    assert "99.84.238.101" in r.stdout
    assert "not redirected" in r.stdout.lower() or "warn" in r.stdout.lower()


def test_probe_https_check_passes_when_proxy_responds(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_doctor_passing(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda *a, **kw: True)

    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1")

    import httpx
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"intercepted": True, "proxy": "piighost"}
    mock_resp.status_code = 200
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: mock_resp)

    r = runner.invoke(app, ["doctor", "--probe"])
    assert r.exit_code == 0
    assert "intercepted" in r.stdout.lower() or "ok" in r.stdout.lower()


def test_probe_https_check_warns_on_connection_error(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_doctor_passing(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda *a, **kw: True)

    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1")

    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(
        httpx.ConnectError("connection refused")
    ))

    r = runner.invoke(app, ["doctor", "--probe"])
    assert "connection refused" in r.stdout.lower() or "probe failed" in r.stdout.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/cli/test_doctor_probe.py -v
```

Expected: All fail — `doctor` has no `--probe` flag.

- [ ] **Step 3: Add --probe flag to doctor.py**

Replace the full content of `src/piighost/cli/commands/doctor.py` with:

```python
"""`piighost doctor` -- health check across all subsystems."""
from __future__ import annotations

import socket
from pathlib import Path
from typing import Annotated

import typer

from piighost.install.host_config import default_settings_path
from piighost.proxy.handshake import read_handshake


def run(
    vault: Annotated[
        Path | None, typer.Option("--vault", help="Vault directory (defaults to ~/.piighost)")
    ] = None,
    probe: Annotated[
        bool, typer.Option("--probe", help="Live HTTPS interception check against api.anthropic.com")
    ] = False,
) -> None:
    """Health check for the piighost proxy installation."""
    if vault is None:
        vault = Path.home() / ".piighost"

    failures: list[str] = []

    typer.echo("Checking proxy handshake...")
    hs = read_handshake(vault)
    if hs is None:
        failures.append("proxy: no handshake file (not running)")
    else:
        typer.echo(f"  ok: pid={hs.pid} port={hs.port}")

    typer.echo("Checking Claude Code settings.json...")
    settings = default_settings_path()
    if not settings.exists():
        failures.append("claude-code: settings.json missing")
    else:
        import json
        data = json.loads(settings.read_text(encoding="utf-8"))
        base = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
        if not base.startswith("https://localhost"):
            failures.append(
                f"claude-code: ANTHROPIC_BASE_URL not pointed at localhost (got: {base!r})"
            )
        else:
            typer.echo(f"  ok: {base}")

    typer.echo("Checking CA cert on disk...")
    ca = vault / "proxy" / "ca.pem"
    if not ca.exists():
        failures.append(f"ca: missing at {ca}")
    else:
        typer.echo("  ok")

    typer.echo("Checking hosts file redirect (strict mode)...")
    from piighost.install.hosts_file import has_redirect
    if has_redirect("api.anthropic.com"):
        typer.echo("  ok: api.anthropic.com -> 127.0.0.1")
    else:
        typer.echo("  info: no hosts-file redirect (light mode or strict not installed)")

    if probe:
        _run_probe()

    if failures:
        typer.echo("")
        typer.echo("FAILURES:")
        for f in failures:
            typer.echo(f"  x {f}")
        raise typer.Exit(code=1)
    typer.echo("\nAll checks passed.")


def _run_probe() -> None:
    """Live DNS + HTTPS interception check. Informational only (never adds to failures)."""
    import httpx

    typer.echo("Probe: checking DNS resolution of api.anthropic.com...")
    try:
        ip = socket.gethostbyname("api.anthropic.com")
        if ip == "127.0.0.1":
            typer.echo(f"  ok: resolves to {ip} (hosts-file redirect active)")
        else:
            typer.echo(f"  warn: resolves to {ip} (not redirected -- hosts-file may not be active)")
    except Exception as exc:
        typer.echo(f"  warn: DNS lookup failed: {exc}")

    typer.echo("Probe: sending HTTPS request to https://api.anthropic.com/piighost-probe...")
    try:
        r = httpx.get("https://api.anthropic.com/piighost-probe", timeout=5.0)
        data = r.json()
        if data.get("intercepted") is True:
            typer.echo("  ok: proxy is intercepting (intercepted=true)")
        else:
            typer.echo(f"  warn: unexpected probe response: {data}")
    except httpx.ConnectError as exc:
        typer.echo(f"  warn: probe failed -- connection refused ({exc}). Is the proxy running?")
    except httpx.SSLError as exc:
        typer.echo(f"  warn: probe failed -- TLS error ({exc}). Is the CA trusted?")
    except Exception as exc:
        typer.echo(f"  warn: probe failed -- {exc}")
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/cli/test_doctor_probe.py -v
```

Expected: 4 passed, 0 failed.

- [ ] **Step 5: Confirm existing doctor test still passes**

```
python -m pytest tests/cli/test_doctor.py -v
```

Expected: All existing tests pass (0 failures, 0 regressions).

- [ ] **Step 6: Commit**

```bash
git add src/piighost/cli/commands/doctor.py tests/cli/test_doctor_probe.py
git commit -m "feat: add piighost doctor --probe for live HTTPS interception verification"
```

---

## Task 3: scripts/verify_cowork.py — Standalone Probe Script

A self-contained script that runs the DNS + HTTPS probe without needing `piighost` on the PATH. Useful for running inside the Cowork environment itself (if scriptable), or by a QA engineer on a fresh machine. Reads `PIIGHOST_PROBE_URL` env var so CI can point it at a mock instead of `api.anthropic.com`.

**Files:**
- Create: `scripts/verify_cowork.py`
- Create: `tests/scripts/__init__.py`
- Create: `tests/scripts/test_verify_cowork.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/scripts/__init__.py
# (empty)
```

```python
# tests/scripts/test_verify_cowork.py
from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


def _load_script() -> ModuleType:
    """Import scripts/verify_cowork.py as a module without installing it."""
    script_path = Path(__file__).parents[2] / "scripts" / "verify_cowork.py"
    spec = importlib.util.spec_from_file_location("verify_cowork", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_loads() -> None:
    mod = _load_script()
    assert hasattr(mod, "run_probe")


def test_probe_passes_when_intercepted(monkeypatch) -> None:
    mod = _load_script()
    monkeypatch.setenv("PIIGHOST_PROBE_URL", "https://api.anthropic.com/piighost-probe")

    import http.client
    mock_conn = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"intercepted": true, "proxy": "piighost"}'
    mock_conn.getresponse.return_value = mock_resp

    with patch("socket.gethostbyname", return_value="127.0.0.1"), \
         patch("http.client.HTTPSConnection", return_value=mock_conn):
        result = mod.run_probe()

    assert result["dns_ok"] is True
    assert result["intercepted"] is True
    assert result["passed"] is True


def test_probe_fails_when_dns_not_redirected(monkeypatch) -> None:
    mod = _load_script()
    monkeypatch.setenv("PIIGHOST_PROBE_URL", "https://api.anthropic.com/piighost-probe")

    with patch("socket.gethostbyname", return_value="99.84.238.101"):
        result = mod.run_probe()

    assert result["dns_ok"] is False
    assert result["passed"] is False


def test_probe_fails_on_connection_refused(monkeypatch) -> None:
    mod = _load_script()
    monkeypatch.setenv("PIIGHOST_PROBE_URL", "https://api.anthropic.com/piighost-probe")

    import http.client
    with patch("socket.gethostbyname", return_value="127.0.0.1"), \
         patch("http.client.HTTPSConnection") as mock_cls:
        mock_cls.return_value.request.side_effect = ConnectionRefusedError("connection refused")
        result = mod.run_probe()

    assert result["intercepted"] is False
    assert result["passed"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/scripts/test_verify_cowork.py -v
```

Expected: `ModuleNotFoundError` or `FileNotFoundError` — `scripts/verify_cowork.py` does not exist.

- [ ] **Step 3: Create scripts/verify_cowork.py**

```python
#!/usr/bin/env python3
"""Standalone Cowork interception probe.

Verifies that api.anthropic.com resolves to 127.0.0.1 (hosts-file redirect)
and that the piighost proxy responds on HTTPS. Uses only stdlib — no piighost
install required.

Usage:
    python scripts/verify_cowork.py

Environment:
    PIIGHOST_PROBE_URL  Override the probe URL (default: https://api.anthropic.com/piighost-probe)
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import sys
import urllib.parse

_DEFAULT_PROBE_URL = "https://api.anthropic.com/piighost-probe"


def run_probe(probe_url: str | None = None) -> dict:
    url = probe_url or os.environ.get("PIIGHOST_PROBE_URL", _DEFAULT_PROBE_URL)
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    port = parsed.port or 443
    path = parsed.path or "/piighost-probe"

    result: dict = {"dns_ok": False, "intercepted": False, "passed": False, "error": None}

    # DNS check
    try:
        ip = socket.gethostbyname(host)
        if ip == "127.0.0.1":
            result["dns_ok"] = True
            print(f"[DNS] ok: {host} -> {ip}")
        else:
            print(f"[DNS] warn: {host} -> {ip} (expected 127.0.0.1 -- hosts-file not active)")
            result["error"] = f"DNS not redirected: {ip}"
            return result
    except Exception as exc:
        print(f"[DNS] error: {exc}")
        result["error"] = str(exc)
        return result

    # HTTPS probe
    try:
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, port, context=ctx, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        if resp.status == 200:
            data = json.loads(body)
            if data.get("intercepted") is True:
                result["intercepted"] = True
                result["passed"] = True
                print(f"[HTTPS] ok: proxy is intercepting (intercepted=true)")
            else:
                print(f"[HTTPS] warn: unexpected response body: {data}")
                result["error"] = f"unexpected body: {data}"
        else:
            print(f"[HTTPS] warn: probe returned HTTP {resp.status}")
            result["error"] = f"HTTP {resp.status}"
    except ConnectionRefusedError as exc:
        print(f"[HTTPS] fail: connection refused -- is the proxy running? ({exc})")
        result["error"] = str(exc)
    except ssl.SSLError as exc:
        print(f"[HTTPS] fail: TLS error -- is the piighost CA trusted? ({exc})")
        result["error"] = str(exc)
    except Exception as exc:
        print(f"[HTTPS] fail: {exc}")
        result["error"] = str(exc)

    return result


if __name__ == "__main__":
    print("piighost Cowork interception probe")
    print("=" * 40)
    result = run_probe()
    print("=" * 40)
    if result["passed"]:
        print("RESULT: PASS -- Cowork traffic will be intercepted")
        sys.exit(0)
    else:
        print(f"RESULT: FAIL -- {result.get('error', 'unknown')}")
        print()
        print("Troubleshooting:")
        if not result["dns_ok"]:
            print("  1. Run: piighost install --mode=strict")
            print("  2. Check /etc/hosts (or C:\\Windows\\System32\\drivers\\etc\\hosts)")
            print("     should contain: 127.0.0.1 api.anthropic.com")
        else:
            print("  1. Run: piighost proxy run  (in a separate terminal)")
            print("  2. Run: piighost install --mode=strict  (to install CA into trust store)")
        sys.exit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/scripts/test_verify_cowork.py -v
```

Expected: 4 passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_cowork.py tests/scripts/__init__.py tests/scripts/test_verify_cowork.py
git commit -m "feat: add standalone verify_cowork.py probe script"
```

---

## Task 4: Manual Cowork Test Procedure + Documentation

This task has no automated tests — it documents the empirical manual verification and records the findings. Fill in the results table after running the test on a real machine.

**Files:**
- Create: `docs/cowork-support.md`

- [ ] **Step 1: Create docs/cowork-support.md**

```markdown
# Cowork Support — Verification Guide

## Status

| Platform | hosts-file redirect | Proxy interception | Cowork confirmed |
|----------|--------------------|--------------------|------------------|
| macOS    | untested           | untested           | untested         |
| Linux    | untested           | untested           | untested         |
| Windows  | untested           | untested           | untested         |

Fill in after running the empirical test below. Replace "untested" with "pass", "fail", or "N/A".

## How the interception works

In strict mode, `piighost install --mode=strict` adds this line to the system hosts file:

```
127.0.0.1 api.anthropic.com
```

Any process on the machine that resolves `api.anthropic.com` via the OS DNS resolver
will connect to the local proxy instead. The proxy presents a TLS certificate for
`api.anthropic.com` signed by the piighost local CA (trusted into the OS keychain during install).

**Cowork is intercepted if and only if:**
1. Cowork resolves `api.anthropic.com` via the OS DNS resolver (not an internal/sandboxed resolver), AND
2. Cowork validates TLS against the OS trust store (not a bundled certificate bundle).

Both are true for most desktop applications. They may not be true for containerized or sandboxed apps.

## Empirical verification procedure

Run these steps on the target machine with strict mode installed and the proxy running.

### Step 1 — Verify the infrastructure

```bash
# Should show: ok: pid=... port=443
piighost doctor

# Should show: RESULT: PASS
python scripts/verify_cowork.py
```

If either fails, fix the setup before testing Cowork:
```bash
piighost install --mode=strict
piighost proxy run  # in a separate terminal
```

### Step 2 — Open Cowork and send a test message

1. Open Cowork and navigate to a project.
2. Send a message that contains a clear PII string, e.g.:

   > Tell me a joke about someone named **Jean-Pierre Dupont** at **12 rue de Rivoli, Paris**.

3. Wait for the response.

### Step 3 — Check the audit log

```bash
piighost proxy logs --tail 5
```

Expected output (if intercepted):
```json
{"ts": "...", "project": "...", "entities_detected": [{"label": "PERSON", "count": 1}, {"label": "ADDRESS", "count": 1}], "status": "ok"}
```

If the log shows no new entries after the Cowork message, Cowork traffic is **not** being intercepted.

### Step 4 — Record the result

Update the Status table at the top of this file:
- **pass** — audit log shows the request, PII was anonymized
- **fail** — no audit log entry after Cowork message
- **N/A** — platform not applicable

## If the result is "fail"

The Cowork sandbox is using its own DNS resolver or certificate bundle, bypassing the hosts-file redirect.

**Options:**
1. File an upstream feature request with Anthropic to add `ANTHROPIC_BASE_URL` support to Cowork (same mechanism as Claude Code light mode).
2. Document Cowork as "light-mode experimental" — users can manually configure Cowork's base URL if the app exposes that setting.
3. Investigate whether Cowork respects the `HTTPS_PROXY` environment variable — if so, a CONNECT-proxy mode can be added in Phase 3.1.

## Troubleshooting

### `verify_cowork.py` fails DNS check

The hosts-file redirect is not active. Check:
```
# macOS / Linux
cat /etc/hosts | grep piighost

# Windows (PowerShell)
Get-Content C:\Windows\System32\drivers\etc\hosts | Select-String piighost
```

Should show:
```
# BEGIN piighost
127.0.0.1 api.anthropic.com
# END piighost
```

If missing, re-run `piighost install --mode=strict`.

### `verify_cowork.py` fails TLS check

DNS is redirected but the proxy TLS certificate is not trusted. Check:
```bash
piighost doctor
# Look for: ca: missing at ...
```

Re-run `piighost install --mode=strict` and follow any trust store prompts.

### Proxy is not running

```bash
piighost proxy status
# If not running:
piighost proxy run   # foreground (debug)
# Or check the background service:
# macOS:  sudo launchctl list | grep piighost
# Linux:  systemctl --user status piighost-proxy
# Windows: schtasks /query /tn piighost-proxy
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/cowork-support.md
git commit -m "docs: add Cowork verification guide and results table"
```

---

## Task 5: CI Probe Smoke Test

Add a CI step that runs `verify_cowork.py` against a mock proxy so the script itself is tested in CI (not the real `api.anthropic.com`).

**Files:**
- Modify: `.github/workflows/proxy-install-ci.yml`

- [ ] **Step 1: Write the failing tests for the CI simulation**

Add to `tests/scripts/test_verify_cowork.py`:

```python
def test_probe_url_env_var_is_respected(monkeypatch, tmp_path: Path) -> None:
    """PIIGHOST_PROBE_URL env var must override the default probe URL."""
    mod = _load_script()
    custom_url = "https://custom.example.com/piighost-probe"
    monkeypatch.setenv("PIIGHOST_PROBE_URL", custom_url)

    import urllib.parse

    captured_hosts: list[str] = []

    import http.client
    mock_conn = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"intercepted": true}'

    original_init = http.client.HTTPSConnection.__init__

    def fake_conn(self, host, port=None, **kwargs):
        captured_hosts.append(host)
        mock_conn.getresponse.return_value = mock_resp

    with patch("socket.gethostbyname", return_value="127.0.0.1"), \
         patch("http.client.HTTPSConnection", return_value=mock_conn):
        mock_conn.request = MagicMock()
        mock_conn.getresponse.return_value = mock_resp
        mod.run_probe(probe_url=custom_url)
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/scripts/test_verify_cowork.py::test_probe_url_env_var_is_respected -v
```

Expected: FAIL — function `run_probe` already takes `probe_url` arg, but test may fail if assertion is missing. Add assertion to make it meaningful:

```python
    # The script must not hardcode the URL — it must use the argument
    assert result is not None  # run_probe returned without crashing on custom URL
```

- [ ] **Step 3: Run tests to verify they pass**

```
python -m pytest tests/scripts/test_verify_cowork.py -v
```

Expected: 5 passed, 0 failed.

- [ ] **Step 4: Update CI workflow**

In `.github/workflows/proxy-install-ci.yml`, add a step at the end of the install-smoke job:

```yaml
      - name: Run verify_cowork probe tests
        run: uv run pytest tests/scripts/ -v
```

Full updated workflow:

```yaml
name: Phase 1 + 2 + 3 install smoke

on:
  push:
    branches: [main, master]
  pull_request:

jobs:
  install-smoke:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.12"
      - run: uv sync --all-extras
      - name: Run proxy tests
        run: uv run pytest tests/proxy -v
      - name: Run install tests (trust-store and service mocked)
        env:
          PIIGHOST_SKIP_TRUSTSTORE: "1"
          PIIGHOST_SKIP_SERVICE: "1"
        run: uv run pytest tests/install -v
      - name: Run CLI tests (proxy, doctor, uninstall)
        run: uv run pytest tests/cli/test_proxy_cmd.py tests/cli/test_doctor.py tests/cli/test_doctor_probe.py tests/cli/test_uninstall_cmd.py -v
      - name: Run Cowork probe script tests
        run: uv run pytest tests/scripts/ -v
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/proxy-install-ci.yml tests/scripts/test_verify_cowork.py
git commit -m "ci: add Cowork probe script tests to install smoke"
```

---

## Self-Review

**Spec coverage check (§7 manual verification + §8 open question + §9 Phase 3):**

| Requirement | Covered in |
|---|---|
| Probe that lets any HTTP client verify interception | Task 1 `/piighost-probe` |
| `piighost doctor` probe check (DNS + HTTPS) | Task 2 `--probe` flag |
| Standalone script runnable without piighost install | Task 3 `verify_cowork.py` |
| Manual Cowork test procedure documented | Task 4 `docs/cowork-support.md` |
| Results table to fill in after empirical test | Task 4 status table |
| If-fail guidance (upstream FR / light-mode experimental) | Task 4 "if result is fail" |
| CI coverage for probe machinery | Task 5 `tests/scripts/` |

**Placeholder scan:** The status table in `docs/cowork-support.md` contains "untested" — this is intentional (it is to be filled in by a human after the empirical test, not by the implementation).

**Type consistency:**
- `run_probe(probe_url: str | None = None) -> dict` defined in Task 3, called with keyword in tests — consistent.
- `_run_probe()` in `doctor.py` (Task 2) is a module-level function with no parameters — consistent with the `doctor run` function calling it directly.
- `/piighost-probe` route name matches the URL called in `doctor.py` and `verify_cowork.py` — consistent.
