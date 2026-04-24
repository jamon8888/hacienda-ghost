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
