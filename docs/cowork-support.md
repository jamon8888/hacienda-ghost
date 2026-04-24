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
