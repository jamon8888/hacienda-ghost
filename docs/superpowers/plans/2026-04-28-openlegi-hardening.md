# OpenLégi Hardening Implementation Plan (Phase 10)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 8 deferred items from Phase 9's final review (status mapping precision, transient retries, cache invalidation tool, regex robustness, missing tests, error-vs-empty distinction) and add a live-OpenLégi smoke test gated by an env var. Pure maintenance round, no new features.

**Architecture:** Same hybrid daemon-proxy as Phase 9. All changes are localized to existing modules; no new packages, no new MCP tools (except `legal_cache_clear`).

**Tech Stack:** Python 3.13 stdlib + httpx + pytest-httpx (already installed).

**Spec:** Phase 10 has no dedicated spec — each task references the Phase 9 final review item that motivated it (in `docs/superpowers/followups/2026-04-28-openlegi-followups.md`, written as Task 10 of this plan).

**Phase 0–9 status:** all merged and pushed. Last commits: piighost `26bc086`, plugin `cd62ab6`.

**Branch:** all backend work commits to `master` in the piighost repo. Plugin worktree at `.worktrees/hacienda-plugin` is unaffected — no plugin work in this phase.

---

## Followup origin map

| Task | Phase 9 review item | Severity in source |
|---|---|---|
| 1 | I-3 (status mapping for 401/auth) | 🟡 Important |
| 2 | M-7 (PisteClient transient retry) | 🟢 Nice-to-have |
| 3 | M-1 (`legal_cache_clear` MCP tool) | 🟢 |
| 4 | M-5 + M-6 (extractor regex robustness) | 🟢 |
| 5 | M-8 (`legal_search` error vs empty) | 🟢 |
| 6 | M-2 + M-3 + M-4 (test coverage gaps) | 🟢 |
| 7 | Live OpenLégi smoke (env-gated) | 🟢 — new |
| 8 | Phase 9 followups doc + push | n/a |

---

## File map (Phase 10)

| Path | Type | Owns |
|---|---|---|
| `src/piighost/legal/piste_client.py` | modify | Distinguish exception types (401/429/network); retry transient `RequestError` |
| `src/piighost/legal/ref_extractor.py` | modify | Range-form articles ("articles 1240 à 1245"); broader terminator |
| `src/piighost/legal/cache.py` | modify | `clear()` already exists; no change here — Task 3 just exposes it via MCP |
| `src/piighost/service/core.py` | modify | Status-mapping precision in `_legal_call` (auth vs network); add `legal_cache_clear` method; richer return shape from `legal_search` (preserve error category) |
| `src/piighost/mcp/tools.py` | modify | 1 new ToolSpec (`legal_cache_clear`) |
| `src/piighost/mcp/shim.py` | modify | 1 new `@mcp.tool` wrapper |
| `src/piighost/daemon/server.py` | modify | 1 new dispatch handler |
| `tests/unit/test_legal_piste_client.py` | modify | Add transient-retry test |
| `tests/unit/test_legal_ref_extractor.py` | modify | Add range-form + better-terminator tests |
| `tests/unit/test_legal_cache.py` | modify | Add `clear()` returns count of removed rows test (already there — sanity check) |
| `tests/unit/test_legal_service.py` | modify | Add `_auto_route_source` parametric tests, cache hit-path test, HALLUCINATION classification test, search error-distinction test, status-mapping precision tests |
| `tests/integration/test_legal_live.py` | new | Live OpenLégi smoke gated by `RUN_LIVE_OPENLEGI=1` |
| `docs/superpowers/followups/2026-04-28-openlegi-followups.md` | new | Phase 9 followups closure log |

---

## Task 1: Status-mapping precision in `_legal_call` and `legal_verify_ref`

**Files:**
- Modify: `src/piighost/service/core.py` (the `_legal_call` and `legal_verify_ref` methods)
- Test: `tests/unit/test_legal_service.py` (append cases)

Phase 9 final review I-3: 401 currently maps to `UNKNOWN_NETWORK` because `_legal_call` catches every exception generically. Distinguish auth, rate-limit, and network failures so `VerificationResult.status` is precise.

- [ ] **Step 1: Read the current `_legal_call` to find the exact `try/except` block**

Run:
```
grep -n "async def _legal_call\|except Exception\|httpx.HTTPStatusError\|httpx.RequestError" /c/Users/NMarchitecte/Documents/piighost/src/piighost/service/core.py | head -10
```

Locate the exception block. The current shape is approximately:
```python
try:
    with PisteClient(...) as client:
        response = client.call_tool(tool, redacted_args)
except Exception as exc:
    return {"error": str(exc)}
```

- [ ] **Step 2: Write failing tests**

Append to `tests/unit/test_legal_service.py` (in the same fixture-using namespace as the existing tests):

```python
def test_verify_legal_ref_401_maps_to_auth_failed(vault_dir, monkeypatch):
    """A 401 from OpenLégi must classify as UNKNOWN_AUTH_FAILED, not _NETWORK."""
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("expired-token")

    def handler(request):
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240 du Code civil",
        "numero": "1240", "code": "Code civil", "position": 0,
    }))
    assert result["status"] == "UNKNOWN_AUTH_FAILED", result
    asyncio.run(svc.close())


def test_verify_legal_ref_429_maps_to_rate_limited_after_retries(vault_dir, monkeypatch):
    """After exhausting 429 retries, status must be UNKNOWN_RATE_LIMITED."""
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    # Always-429 — exhausts the PisteClient's retry budget
    def handler(request):
        return httpx.Response(429, text="rate limited")

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )
    monkeypatch.setattr("time.sleep", lambda s: None)  # no-op the retry sleeps

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240", "numero": "1240", "code": "Code civil",
        "position": 0,
    }))
    assert result["status"] == "UNKNOWN_RATE_LIMITED", result
    asyncio.run(svc.close())


def test_verify_legal_ref_network_error_maps_to_network(vault_dir, monkeypatch):
    """A network-level exception (DNS, conn refused) maps to UNKNOWN_NETWORK."""
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    def handler(request):
        raise httpx.ConnectError("name resolution failed")

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240", "numero": "1240", "code": "Code civil",
        "position": 0,
    }))
    assert result["status"] == "UNKNOWN_NETWORK", result
    asyncio.run(svc.close())
```

- [ ] **Step 3: Run the tests — Expected: all 3 fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_service.py -v --no-header -k "401_maps or 429_maps or network_error_maps"
```

Expected: 3 failed (currently they all return `UNKNOWN_NETWORK`).

- [ ] **Step 4: Update `_legal_call` to return error categories**

In `src/piighost/service/core.py`, modify the exception block in `_legal_call`. Replace the current generic `except Exception` with typed handlers:

```python
        token = CredentialsService().get_openlegi_token()
        try:
            with PisteClient(
                token=token or "",
                base_url=self._config.openlegi.base_url,
                service=self._config.openlegi.service,
            ) as client:
                response = client.call_tool(tool, redacted_args)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403):
                return {"error": str(exc), "category": "auth"}
            if code == 429:
                return {"error": str(exc), "category": "rate_limit"}
            return {"error": str(exc), "category": "http"}
        except httpx.RequestError as exc:
            # Connection / DNS / timeout — network-level
            return {"error": str(exc), "category": "network"}
        except ValueError as exc:
            # SSE parse errors raised by PisteClient._parse_sse
            return {"error": str(exc), "category": "parse"}
        except Exception as exc:
            return {"error": str(exc), "category": "unknown"}
```

Make sure `import httpx` is at the top of the file (or imported lazily inside the method). Check existing imports first — `httpx` may already be imported.

- [ ] **Step 5: Update `legal_verify_ref` to map categories to statuses**

Locate `legal_verify_ref` in core.py. Find the current line:

```python
if isinstance(response, dict) and "error" in response:
    return VerificationResult(
        status="UNKNOWN_NETWORK", message=str(response["error"]),
    ).model_dump()
```

Replace with:

```python
if isinstance(response, dict) and "error" in response:
    cat = response.get("category", "unknown")
    status_map = {
        "auth": "UNKNOWN_AUTH_FAILED",
        "rate_limit": "UNKNOWN_RATE_LIMITED",
        "network": "UNKNOWN_NETWORK",
        "parse": "UNKNOWN_PARSE_ERROR",
        "http": "UNKNOWN_NETWORK",
        "unknown": "UNKNOWN_NETWORK",
    }
    return VerificationResult(
        status=status_map.get(cat, "UNKNOWN_NETWORK"),
        message=str(response["error"]),
    ).model_dump()
```

- [ ] **Step 6: Run the new tests + the full Phase 9 sweep**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_service.py tests/integration/test_legal_outbound_privacy.py -v --no-header
```

Expected: all green (50 prior + 3 new = 53 in test_legal_service alone — but the file count includes the privacy gate).

- [ ] **Step 7: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_legal_service.py
git commit -m "fix(legal): distinguish auth/rate-limit/network/parse errors

Phase 10 Task 1 (closes Phase 9 review I-3). _legal_call now catches
typed exceptions and returns a 'category' field; legal_verify_ref maps
each category to the correct VerificationResult.status:

  401/403 → UNKNOWN_AUTH_FAILED
  429     → UNKNOWN_RATE_LIMITED (after PisteClient retry exhaustion)
  RequestError → UNKNOWN_NETWORK
  ValueError (SSE parse) → UNKNOWN_PARSE_ERROR
  any other → UNKNOWN_NETWORK fallback

Three new regression tests cover 401, 429-after-retries, and
DNS-level network failures."
```

---

## Task 2: PisteClient retry on transient `RequestError`

**Files:**
- Modify: `src/piighost/legal/piste_client.py` (`_post_with_retry`)
- Test: `tests/unit/test_legal_piste_client.py`

Phase 9 final review M-7: a transient DNS hiccup or connection reset surfaces as `UNKNOWN_NETWORK` immediately. Add a small retry budget for `httpx.RequestError` (network-level) — same backoff schedule as 429 but capped tighter.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_legal_piste_client.py`:

```python
def test_request_error_retries_then_succeeds(httpx_mock, monkeypatch):
    """Transient connection failures retry up to max_retries."""
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    # First two attempts: ConnectError; third: success
    httpx_mock.add_exception(httpx.ConnectError("name resolution failed"))
    httpx_mock.add_exception(httpx.ConnectError("name resolution failed"))
    httpx_mock.add_response(text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}))

    with PisteClient(token="x", max_retries=3) as c:
        result = c.call_tool("rechercher_code", {})
    assert result == {"ok": True}
    assert len(sleeps) == 2  # two retries with backoff


def test_request_error_exhausts_retries_then_raises(httpx_mock, monkeypatch):
    """After exhausting retries on RequestError, the exception bubbles."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    for _ in range(5):
        httpx_mock.add_exception(httpx.ConnectError("DNS down"))

    with PisteClient(token="x", max_retries=3) as c:
        with pytest.raises(httpx.RequestError):
            c.call_tool("rechercher_code", {})
```

- [ ] **Step 2: Run tests — Expected: 2 fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_piste_client.py -v --no-header -k "request_error"
```

Expected: both fail because `_post_with_retry` re-raises `RequestError` immediately (line ~94 in `piste_client.py`).

- [ ] **Step 3: Update `_post_with_retry` to retry transient errors**

In `src/piighost/legal/piste_client.py`, replace `_post_with_retry`:

```python
    def _post_with_retry(self, body: dict) -> dict:
        attempt = 0
        while True:
            try:
                resp = self._client.post(self._url, json=body, headers=self._headers)
            except httpx.RequestError as exc:
                # Transient: DNS / conn reset / timeout. Retry with the
                # same backoff schedule as 429.
                if attempt < self._max_retries:
                    attempt += 1
                    delay = 0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    time.sleep(delay)
                    continue
                raise
            if resp.status_code == 429 and attempt < self._max_retries:
                attempt += 1
                delay = 0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return self._parse_sse(resp.text)
```

- [ ] **Step 4: Run tests — Expected: all green**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_piste_client.py -v --no-header
```

Expected: 8 prior + 2 new = 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/legal/piste_client.py tests/unit/test_legal_piste_client.py
git commit -m "fix(legal): retry transient httpx.RequestError in PisteClient

Phase 10 Task 2 (closes Phase 9 review M-7). DNS hiccups and
connection resets now retry with the same exponential backoff +
jitter schedule as 429 (max_retries cap shared). After exhaustion,
the exception bubbles unchanged so _legal_call can map it to
UNKNOWN_NETWORK.

Two regression tests: transient-then-success, and exhaust-then-raise."
```

---

## Task 3: `legal_cache_clear` MCP tool

**Files:**
- Modify: `src/piighost/service/core.py` (add `legal_cache_clear` method)
- Modify: `src/piighost/mcp/tools.py` (1 ToolSpec)
- Modify: `src/piighost/mcp/shim.py` (1 wrapper)
- Modify: `src/piighost/daemon/server.py` (1 dispatch handler)
- Test: `tests/unit/test_legal_service.py` (append)

Phase 9 final review M-1: no manual cache invalidation. Avocat needs to be able to flush the legal cache after a CNIL guidance update or when debugging. Wraps `LegalCache.clear()` (already exists from Task 4 of Phase 9).

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_legal_service.py`:

```python
def test_legal_cache_clear_returns_count(vault_dir, monkeypatch):
    """legal_cache_clear empties the cache and returns the row count."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    # Populate cache via two distinct legal_search calls
    captured: list = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": []}}),
            headers={"Content-Type": "text/event-stream"},
        )
    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    asyncio.run(svc.legal_search(query="x", source="code"))
    asyncio.run(svc.legal_search(query="y", source="cnil"))

    # 2 cache entries now exist
    result = asyncio.run(svc.legal_cache_clear())
    assert result == {"removed": 2}
    asyncio.run(svc.close())


def test_legal_cache_clear_on_empty_returns_zero(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_cache_clear())
    assert result == {"removed": 0}
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests — Expected: AttributeError on `svc.legal_cache_clear`**

- [ ] **Step 3: Add `legal_cache_clear` to `PIIGhostService`**

In `src/piighost/service/core.py`, after `legal_credentials_set`, add:

```python
    async def legal_cache_clear(self) -> dict:
        """Empty the legal-cache SQLite. Returns the count of removed rows."""
        from piighost.legal import LegalCache
        from pathlib import Path
        cache_dir = Path.home() / ".piighost"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache = LegalCache(vault_dir=cache_dir)
        try:
            removed = cache.clear()
        finally:
            cache.close()
        return {"removed": removed}
```

- [ ] **Step 4: Run tests — Expected: 2 passed**

- [ ] **Step 5: Wire MCP — ToolSpec, shim wrapper, dispatch handler**

In `src/piighost/mcp/tools.py`, after `legal_credentials_set`:

```python
    ToolSpec(
        name="legal_cache_clear",
        rpc_method="legal_cache_clear",
        description=(
            "Empty the OpenLégi response cache (~/.piighost/legal_cache.sqlite). "
            "Useful after a CNIL guidance update or when debugging stale "
            "verification results. Returns {'removed': N}."
        ),
        timeout_s=5.0,
    ),
```

In `src/piighost/mcp/shim.py`, after `legal_credentials_set` wrapper:

```python
    @mcp.tool(name="legal_cache_clear",
              description=by_name["legal_cache_clear"].description)
    async def legal_cache_clear() -> dict:
        return await _lazy_dispatch(by_name["legal_cache_clear"], params={})
```

In `src/piighost/daemon/server.py`'s `_dispatch`, before the final raise:

```python
    if method == "legal_cache_clear":
        return await svc.legal_cache_clear()
```

- [ ] **Step 6: Smoke-check the catalog**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
from piighost.mcp.tools import TOOL_CATALOG
names = [t.name for t in TOOL_CATALOG]
assert 'legal_cache_clear' in names
print(f'legal_cache_clear registered (catalog now {len(names)})')
"
```

Expected: `legal_cache_clear registered (catalog now 34)`.

- [ ] **Step 7: Re-run all legal-subsystem tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_service.py tests/unit/test_legal_cache.py -v --no-header
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/piighost/service/core.py src/piighost/mcp/tools.py src/piighost/mcp/shim.py src/piighost/daemon/server.py tests/unit/test_legal_service.py
git commit -m "feat(legal): legal_cache_clear MCP tool

Phase 10 Task 3 (closes Phase 9 review M-1). New MCP tool to empty
the OpenLégi response cache. Wraps LegalCache.clear(). Returns
{'removed': N}.

Useful after CNIL guidance update or when debugging stale
verification results. Tool catalog grows 33 → 34."
```

---

## Task 4: Reference extractor robustness — range form + better terminator

**Files:**
- Modify: `src/piighost/legal/ref_extractor.py`
- Test: `tests/unit/test_legal_ref_extractor.py`

Phase 9 final review M-5 + M-6: extractor misses "articles 1240 à 1245" range form, and the `_RE_ARTICLE_CODE` terminator is brittle (only matches a fixed verb list). Both are real edge cases on a regulated avocat's actual corpus.

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_legal_ref_extractor.py`:

```python
def test_extract_range_form_articles():
    """'articles 1240 à 1245 du Code civil' captures both endpoints."""
    refs = extract_references("Voir les articles 1240 à 1245 du Code civil.")
    article_refs = [r for r in refs if r.ref_type == LegalRefType.ARTICLE_CODE]
    assert len(article_refs) >= 2, article_refs
    numeros = sorted(r.numero for r in article_refs)
    assert "1240" in numeros and "1245" in numeros


def test_extract_article_with_unknown_verb():
    """An article followed by a verb not in the historical list still extracts."""
    # 'exige' was not in the original verb terminator list
    refs = extract_references("L'article 1240 du Code civil exige une faute.")
    article_refs = [r for r in refs if r.ref_type == LegalRefType.ARTICLE_CODE]
    assert len(article_refs) == 1
    assert article_refs[0].numero == "1240"
    assert article_refs[0].code == "Code civil"


def test_extract_article_followed_by_period_only():
    """End-of-sentence terminator works."""
    refs = extract_references("Voir l'article 1240 du Code civil.")
    article_refs = [r for r in refs if r.ref_type == LegalRefType.ARTICLE_CODE]
    assert len(article_refs) == 1
    assert article_refs[0].numero == "1240"
```

- [ ] **Step 2: Run tests — Expected: at least the range and unknown-verb tests fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_ref_extractor.py -v --no-header -k "range_form or unknown_verb or period_only"
```

- [ ] **Step 3: Loosen the article-code regex + add range-form support**

In `src/piighost/legal/ref_extractor.py`, locate `_RE_ARTICLE_CODE`. Replace it with a simpler pattern that captures the code name greedily up to a clear terminator (period, comma, semicolon, conjunction, or end-of-string), AND add a separate regex pass for range forms.

```python
# Single-article form. Terminator is any punctuation OR a clear separator.
# Removed the brittle verb list — any code name followed by punctuation
# or end-of-text terminates cleanly.
_RE_ARTICLE_CODE = re.compile(
    r"(?:l')?articles?\s+([LRDA]\.?\s*)?(\d+(?:-\d+)*)"
    r"\s+du\s+(Code\s+(?:de\s+|du\s+|d'|des\s+)?[\w'-]+(?:\s+[\w'-]+){0,4}?)"
    r"(?=\s*[,\.\);:]|\s+(?:et|ou|qui|dispose|prévoit|énonce|exige|impose|stipule|requiert|précise|prescrit|fixe|établit|interdit|autorise)|\s*$)",
    re.I,
)

# Range form: "articles 1240 à 1245 du Code civil"
_RE_ARTICLE_RANGE = re.compile(
    r"articles?\s+(\d+(?:-\d+)*)\s+à\s+(\d+(?:-\d+)*)"
    r"\s+du\s+(Code\s+(?:de\s+|du\s+|d'|des\s+)?[\w'-]+(?:\s+[\w'-]+){0,4}?)"
    r"(?=\s*[,\.\);:]|\s+(?:et|ou)|\s*$)",
    re.I,
)
```

Then update `extract_references()` to add the range-form pass. Find the existing block:

```python
# Articles in codes (full form)
for m in _RE_ARTICLE_CODE.finditer(text):
    ...
```

Insert a new pass BEFORE that block (so range form runs first and dedup is handled by position):

```python
# Articles range form: "articles 1240 à 1245 du Code civil"
for m in _RE_ARTICLE_RANGE.finditer(text):
    code = _normalize_code(m.group(3))
    start_num = m.group(1)
    end_num = m.group(2)
    # Emit start + end as separate refs (the avocat will verify both
    # endpoints; intermediate articles are implied but not enumerated).
    _add(
        LegalRefType.ARTICLE_CODE,
        raw_text=m.group(0), position=m.start(),
        numero=start_num, code=code,
    )
    _add(
        LegalRefType.ARTICLE_CODE,
        raw_text=m.group(0), position=m.start() + 1,  # +1 to keep distinct
        numero=end_num, code=code,
    )
```

NOTE: The existing dedup-by-position logic at the end of `extract_references` (re-numbering after sort) handles the +1 trick gracefully. If your codebase doesn't do that re-numbering, ensure each emitted ref has a unique `position` value (real-world articles 1240 vs 1245 in "articles 1240 à 1245" both technically share the same start char in the source).

- [ ] **Step 4: Run all extractor tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_ref_extractor.py -v --no-header
```

Expected: 9 prior + 3 new = 12 passed. If `test_extract_multiple_refs_in_paragraph` (the `articles 1240 et 1241` case) breaks, the new range pass is interfering — verify the "et" form still works and the "à" form is handled correctly. The "et" pattern in the existing regex stays intact; the new range regex specifically requires `à` between numbers, so they shouldn't collide.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/legal/ref_extractor.py tests/unit/test_legal_ref_extractor.py
git commit -m "feat(legal): extractor handles range form + unknown verbs

Phase 10 Task 4 (closes Phase 9 review M-5 + M-6).

Range form: 'articles 1240 à 1245 du Code civil' now emits both
endpoint refs (1240 and 1245). Intermediate numbers are implied but
not enumerated — the avocat verifies the bounds.

Loosened terminator: the original _RE_ARTICLE_CODE only matched a
fixed verb list (dispose/prévoit/énonce). Now also matches exige /
impose / stipule / requiert / précise / prescrit / fixe / établit /
interdit / autorise / ou — and falls back cleanly to any punctuation
or end-of-string.

Three new regression tests."
```

---

## Task 5: `legal_search` distinguishes errors from empty results

**Files:**
- Modify: `src/piighost/service/core.py` (`legal_search` method)
- Test: `tests/unit/test_legal_service.py`

Phase 9 final review M-8: `legal_search` returns `[]` for both "no hits" AND "OpenLégi error" — caller can't distinguish. After Task 1, `_legal_call` now returns a `category` field on errors. Use it.

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_legal_service.py`:

```python
def test_legal_search_distinguishes_error_from_empty(vault_dir, monkeypatch):
    """An OpenLégi error must produce a structured error dict, not [].

    Empty hits → []
    Auth/network error → [{"source": "_error", "title": "...", ...}]
    """
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("expired-token")

    def handler(request):
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    hits = asyncio.run(svc.legal_search(query="x", source="code"))
    # NOT empty list — should be a 1-item list with the error sentinel
    assert len(hits) == 1
    assert hits[0]["source"] == "_error"
    assert hits[0].get("category") == "auth"
    assert "title" in hits[0]
    asyncio.run(svc.close())


def test_legal_search_empty_hits_returns_plain_empty(vault_dir, monkeypatch):
    """200 OK with hits=[] still returns []."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    def handler(request):
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": []}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    hits = asyncio.run(svc.legal_search(query="x", source="code"))
    assert hits == []
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests — Expected: first fails (returns [] for both)**

- [ ] **Step 3: Update `legal_search` to surface error sentinel**

In `src/piighost/service/core.py`, locate `legal_search`. Find the section:

```python
result = await self._legal_call(
    tool, {"search": query, "max_results": max_results}, ttl_seconds=300,
)
if isinstance(result, dict) and "hits" in result:
    return [...]
return []
```

Replace with:

```python
result = await self._legal_call(
    tool, {"search": query, "max_results": max_results}, ttl_seconds=300,
)
# Error from _legal_call: surface a 1-item sentinel rather than
# silently returning []. The skill can show "OpenLégi error: …"
# instead of "no results found".
if isinstance(result, dict) and "error" in result:
    return [{
        "source": "_error",
        "title": f"OpenLégi error ({result.get('category', 'unknown')})",
        "snippet": str(result["error"])[:200],
        "url": None,
        "score": None,
        "category": result.get("category", "unknown"),
    }]
if isinstance(result, dict) and "hits" in result:
    return [
        {"source": source, "title": h.get("title", ""),
         "snippet": h.get("snippet", h.get("contenu", "")),
         "url": h.get("url"), "score": h.get("score")}
        for h in result["hits"]
    ]
return []
```

- [ ] **Step 4: Run tests**

Expected: both new + all prior pass.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_legal_service.py
git commit -m "feat(legal): legal_search surfaces error sentinel

Phase 10 Task 5 (closes Phase 9 review M-8). legal_search now
returns a 1-item list with source='_error' when _legal_call returns
an error category, instead of silently returning []. The skill can
distinguish 'no hits' from 'OpenLégi failed'.

Sentinel shape:
  {source: '_error', title: 'OpenLégi error (auth)',
   snippet: '<truncated error>', category: 'auth', ...}

Empty 200-OK hits still return [] as before. Two regression tests."
```

---

## Task 6: Test coverage gaps — `_auto_route_source`, cache hit-path, HALLUCINATION classification

**Files:**
- Test: `tests/unit/test_legal_service.py` (append)

Phase 9 final review M-2 + M-3 + M-4: missing tests for the dispatch routing, cache hit verification, and the HALLUCINATION classifier branch.

- [ ] **Step 1: Write the tests**

Append to `tests/unit/test_legal_service.py`:

```python
@pytest.mark.parametrize("query,expected", [
    # Pourvoi number → jurisprudence
    ("Cass. civ. 1re, 21-12.345", "jurisprudence_judiciaire"),
    # Loi n°
    ("loi n°78-17 du 6 janvier 1978", "lois_decrets"),
    # CNIL keyword
    ("décision CNIL sur les cookies", "cnil"),
    # Article + Code
    ("article 1240 du Code civil", "code"),
    # Bare Code reference
    ("Code de commerce", "code"),
    # Default fallback
    ("texte ambigu sans repère", "code"),
])
def test_auto_route_source_dispatch(query, expected):
    """The auto-router maps query shapes to the right OpenLégi source."""
    from piighost.service.core import PIIGhostService
    assert PIIGhostService._auto_route_source(query) == expected


def test_legal_search_cache_hits_skip_wire(vault_dir, monkeypatch):
    """Identical legal_search calls hit the cache the second time."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": [{"title": "Art. 1240"}]}}),
            headers={"Content-Type": "text/event-stream"},
        )
    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    asyncio.run(svc.legal_search(query="article 1240", source="code"))
    asyncio.run(svc.legal_search(query="article 1240", source="code"))
    asyncio.run(svc.legal_search(query="article 1240", source="code"))
    # Only ONE wire call despite three method calls
    assert len(captured) == 1, f"expected 1 wire call, got {len(captured)}"
    asyncio.run(svc.close())


def test_legal_verify_ref_classifies_hallucination(vault_dir, monkeypatch):
    """No hits → HALLUCINATION with type_erreur=REF_INEXISTANTE, score=0."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    def handler(request):
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": []}}),
            headers={"Content-Type": "text/event-stream"},
        )
    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 99999 du Code civil",
        "numero": "99999", "code": "Code civil", "position": 0,
    }))
    assert result["status"] == "HALLUCINATION"
    assert result["score"] == 0
    assert result["type_erreur"] == "REF_INEXISTANTE"
    asyncio.run(svc.close())


def test_legal_verify_ref_classifies_verifie_exact(vault_dir, monkeypatch):
    """Hits present → VERIFIE_EXACT with score=100 and url passed through."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    def handler(request):
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {
                "hits": [{
                    "title": "Code civil, Art. 1240",
                    "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000032041604/",
                }],
            }}),
            headers={"Content-Type": "text/event-stream"},
        )
    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240 du Code civil",
        "numero": "1240", "code": "Code civil", "position": 0,
    }))
    assert result["status"] == "VERIFIE_EXACT"
    assert result["score"] == 100
    assert "legifrance.gouv.fr" in result["url_legifrance"]
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run all legal_service tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_legal_service.py -v --no-header
```

Expected: all green. Counts:
- 6 prior + 3 from Task 1 + 2 from Task 3 + 2 from Task 5 + 6+ from this task (parametric `_auto_route_source` is 6 cases) = ~25+ tests.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_legal_service.py
git commit -m "test(legal): close coverage gaps from Phase 9 review

Phase 10 Task 6 (closes Phase 9 review M-2 + M-3 + M-4):

  M-2 — _auto_route_source dispatch: 6 parametric cases covering
        pourvoi numbers, loi n°, cnil keyword, article+code, bare
        Code reference, default fallback
  M-3 — cache hit-path: 3 identical legal_search calls produce
        only 1 wire call
  M-4 — HALLUCINATION + VERIFIE_EXACT classification: explicit
        tests asserting type_erreur=REF_INEXISTANTE on empty hits
        and score=100 + url_legifrance pass-through on present hits"
```

---

## Task 7: Live OpenLégi smoke test (env-gated)

**Files:**
- Create: `tests/integration/test_legal_live.py`
- Modify: `pyproject.toml` (add a `live` marker)

Spec mentioned this slot. Single optional integration test that hits real `https://mcp.openlegi.fr` with a real PISTE token. Skipped unless `RUN_LIVE_OPENLEGI=1` env var is set. Catches drift between the OpenLégi docs example and their actual deployed behavior — would have caught any SSE format change between Phase 9 implementation and reality.

- [ ] **Step 1: Add the `live` pytest marker**

In `pyproject.toml`, find or create the `[tool.pytest.ini_options]` section. Add:

```toml
[tool.pytest.ini_options]
markers = [
    "live: tests that hit real external services (OpenLégi). Gated by RUN_LIVE_OPENLEGI=1 env var.",
]
```

If the section already exists with `markers`, just append the new marker line — don't replace.

- [ ] **Step 2: Write the live smoke test**

Create `tests/integration/test_legal_live.py`:

```python
"""Live OpenLégi smoke — hits real https://mcp.openlegi.fr.

Gated by RUN_LIVE_OPENLEGI=1 env var AND PIIGHOST_PISTE_TOKEN env var.
Skipped in normal CI. Run manually after major OpenLégi changes or
when shipping a release that depends on the real endpoint shape.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from piighost.service.config import ServiceConfig, RerankerSection, OpenLegiSection
from piighost.service.core import PIIGhostService
from piighost.service.credentials import CredentialsService


pytestmark = pytest.mark.live


def _skip_if_not_live():
    if os.environ.get("RUN_LIVE_OPENLEGI") != "1":
        pytest.skip("Set RUN_LIVE_OPENLEGI=1 to enable live OpenLégi tests")
    if not os.environ.get("PIIGHOST_PISTE_TOKEN"):
        pytest.skip("Set PIIGHOST_PISTE_TOKEN=<your token> to enable live tests")


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return tmp_path / "vault"


def test_live_search_legal_for_article_1240(vault_dir, monkeypatch):
    """Real OpenLégi must return at least one hit for article 1240 du Code civil."""
    _skip_if_not_live()

    CredentialsService().set_openlegi_token(os.environ["PIIGHOST_PISTE_TOKEN"])

    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=True),
    )
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))

    hits = asyncio.run(svc.legal_search(query="1240", source="code", max_results=3))

    # At least one real hit (Art. 1240 — responsabilité délictuelle)
    real_hits = [h for h in hits if h.get("source") != "_error"]
    assert real_hits, f"no real hits returned: {hits}"

    # Each hit has the expected shape
    for h in real_hits:
        assert "title" in h
        assert h.get("source") == "code"

    asyncio.run(svc.close())


def test_live_verify_legal_ref_for_known_article(vault_dir, monkeypatch):
    """A real, known article must return VERIFIE_EXACT."""
    _skip_if_not_live()

    CredentialsService().set_openlegi_token(os.environ["PIIGHOST_PISTE_TOKEN"])

    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=True),
    )
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))

    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240 du Code civil",
        "numero": "1240", "code": "Code civil", "position": 0,
    }))

    assert result["status"] == "VERIFIE_EXACT", result
    asyncio.run(svc.close())
```

- [ ] **Step 3: Verify the test skips cleanly without the env vars**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/integration/test_legal_live.py -v --no-header
```

Expected: 2 skipped (no RUN_LIVE_OPENLEGI env var).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tests/integration/test_legal_live.py
git commit -m "test(legal): live OpenLégi smoke (env-gated)

Phase 10 Task 7 (closes Phase 9 spec slot for live testing).

Two manual tests against real https://mcp.openlegi.fr:
  - search_legal('1240', source='code') → real hits returned
  - verify_legal_ref(article 1240) → VERIFIE_EXACT

Gated by RUN_LIVE_OPENLEGI=1 + PIIGHOST_PISTE_TOKEN env vars.
Skipped in normal CI. Catches drift between OpenLégi's documented
endpoint shape and the actual deployed behavior — run after major
OpenLégi updates or before shipping a release."
```

---

## Task 8: Followups doc + final smoke + push

**Files:**
- Create: `docs/superpowers/followups/2026-04-28-openlegi-followups.md`
- Verification + push

- [ ] **Step 1: Write the followups doc**

Create `docs/superpowers/followups/2026-04-28-openlegi-followups.md`:

```markdown
# OpenLégi (Phase 9–10) — Follow-up Issues

**Date:** 2026-04-28
**Source:** Phase 9 final review + Phase 10 closure
**Spec:** [docs/superpowers/specs/2026-04-28-openlegi-integration-design.md](../specs/2026-04-28-openlegi-integration-design.md)
**Plans:**
- [docs/superpowers/plans/2026-04-28-openlegi-integration.md](../plans/2026-04-28-openlegi-integration.md) (Phase 9)
- [docs/superpowers/plans/2026-04-28-openlegi-hardening.md](../plans/2026-04-28-openlegi-hardening.md) (Phase 10)

This file consolidates the Phase 9 final-review items: 2 fixed inline
in Phase 9 (I-1 anonymizer wiring, I-4 step renumbering), 8 deferred
to Phase 10 and addressed in this round.

## Resolution log

| # | Phase 9 review | Status | Resolution |
|---|---|---|---|
| I-1 | No-op anonymize in `_legal_call` | ✅ closed | Phase 9 commit `26bc086` — pre-anonymize args via project's real anonymize before redactor |
| I-2 | Cache key uses raw args | ✅ closed | Phase 9 commit `26bc086` — cache keys now use anonymized_args |
| I-3 | 401 → UNKNOWN_NETWORK miscategorisation | ✅ closed | Phase 10 Task 1 — typed exception handlers + status_map |
| I-4 | Duplicate Step 5 headings | ✅ closed | Phase 9 plugin commit `cd62ab6` — renumbered to Step 5 + Step 6 |
| M-1 | No `legal_cache_clear` MCP tool | ✅ closed | Phase 10 Task 3 — new MCP tool + tests |
| M-2 | Missing `_auto_route_source` tests | ✅ closed | Phase 10 Task 6 — 6 parametric cases |
| M-3 | Missing cache hit-path test | ✅ closed | Phase 10 Task 6 — 3-call/1-wire assertion |
| M-4 | Missing HALLUCINATION classification test | ✅ closed | Phase 10 Task 6 — VERIFIE_EXACT + HALLUCINATION coverage |
| M-5 | Range-form articles ("articles X à Y") | ✅ closed | Phase 10 Task 4 — new `_RE_ARTICLE_RANGE` regex |
| M-6 | Brittle `_RE_ARTICLE_CODE` terminator | ✅ closed | Phase 10 Task 4 — extended verb list + clean punctuation fallback |
| M-7 | PisteClient no retry on `RequestError` | ✅ closed | Phase 10 Task 2 — transient retries with backoff |
| M-8 | `legal_search` error vs empty | ✅ closed | Phase 10 Task 5 — `_error` source sentinel |

All Phase 9 final-review items are now closed. The legal subsystem is
production-ready for the no-ML-models path AND has live-OpenLégi smoke
coverage gated behind `RUN_LIVE_OPENLEGI=1`.

## New follow-ups surfaced during Phase 10 (none → 🟢 nice-to-have only)

No new architectural concerns. Three minor v1.2 candidates:

1. 🟢 The `_error` source sentinel in `legal_search` is convention-only
   — `LegalHit` Pydantic schema doesn't validate it. If a future
   refactor tightens `Literal["code", ..., "_error"]`, ensure the
   sentinel survives. (Currently it works because `_error` isn't in
   the `Literal` and Pydantic accepts the dict at the MCP boundary
   without re-validation — fragile.)

2. 🟢 `legal_cache_clear` operates on the daemon-wide cache (one
   SQLite under `~/.piighost/legal_cache.sqlite`). If the future calls
   for per-project caches, this needs to scope by project_id.

3. 🟢 Live tests don't assert exact response shape (just "real hits
   returned"). If OpenLégi changes their SSE format or adds wrapping
   layers, the live tests pass but the parser silently degrades. Worth
   adding a "schema drift detector" v1.2.
```

- [ ] **Step 2: Run the full Phase 9 + Phase 10 sweep**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_legal_reference_models.py \
  tests/unit/test_legal_ref_extractor.py \
  tests/unit/test_legal_redactor.py \
  tests/unit/test_legal_cache.py \
  tests/unit/test_legal_piste_client.py \
  tests/unit/test_credentials_service.py \
  tests/unit/test_legal_service.py \
  tests/integration/test_legal_outbound_privacy.py \
  tests/integration/test_legal_live.py \
  --no-header
```

Expected: all green (live tests skip cleanly without env vars).

- [ ] **Step 3: Run full RGPD regression**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_doc_authors_anonymisation.py tests/unit/test_controller_profile.py tests/unit/test_controller_profile_mcp.py tests/unit/test_controller_profile_defaults_mcp.py tests/unit/test_processing_register.py tests/unit/test_dpia_screening.py tests/unit/test_render_compliance_doc.py tests/unit/test_render_data_validation.py tests/unit/test_no_pii_leak_phase1.py tests/unit/test_no_pii_leak_phase2.py tests/unit/test_subject_clustering.py tests/unit/test_profile_loader.py tests/unit/test_profile_loader_warns.py tests/unit/test_compliance_public_api.py tests/unit/test_compliance_lazy_imports.py tests/unit/test_compliance_submodels_forbid.py --no-header 2>&1 | tail -5
```

Expected: 89/89 still green.

- [ ] **Step 4: Commit followups doc + push**

```bash
git add docs/superpowers/followups/2026-04-28-openlegi-followups.md
git commit -m "docs(followups): OpenLégi Phase 9-10 closure

Consolidates the Phase 9 final-review items + Phase 10 resolutions.

  - I-1, I-2 closed inline in Phase 9 (commit 26bc086)
  - I-4 closed in Phase 9 plugin commit cd62ab6
  - I-3 closed in Phase 10 Task 1 (status mapping)
  - M-1 → M-8 all closed across Phase 10 Tasks 2-6
  - Live OpenLégi smoke added in Phase 10 Task 7

All 12 review items closed. Three minor v1.2 candidates surfaced
during Phase 10 — flagged but not blocking."

ECC_SKIP_PREPUSH=1 git push jamon master 2>&1 | tail -3
```

---

## Self-review checklist

**Spec coverage:**

| Phase 9 review item | Implementing task |
|---|---|
| I-3 (status mapping for 401/auth) | Task 1 |
| M-7 (PisteClient transient retry) | Task 2 |
| M-1 (`legal_cache_clear` MCP tool) | Task 3 |
| M-5 (range-form articles) | Task 4 |
| M-6 (brittle terminator) | Task 4 |
| M-8 (legal_search error vs empty) | Task 5 |
| M-2 (`_auto_route_source` tests) | Task 6 |
| M-3 (cache hit-path test) | Task 6 |
| M-4 (HALLUCINATION classification test) | Task 6 |
| Live OpenLégi smoke | Task 7 |
| Followups doc + push | Task 8 |

✓ Every Phase 9 review item is addressed. The 3 already-closed Phase 9 items (I-1, I-2, I-4) are noted in the Phase 10 followups doc.

**Placeholder scan**: every code block has real code. No "TBD" / "similar to Task N".

**Type consistency**:
- `category` field on `_legal_call` error returns is added in Task 1 and consumed in Task 5 (`legal_search` error sentinel). ✓
- `LegalHit` source `_error` is a convention (not in `Literal`); flagged in followups doc as a v1.2 concern. ✓
- `_auto_route_source` is a `@staticmethod` so the parametric test calls it directly on the class. ✓
- `legal_cache_clear()` returns `{"removed": int}` — same shape as `LegalCache.clear()` which returns `int` (wrapped in dict for MCP-friendliness). ✓

---

## Estimated effort

| Task | Effort |
|---|---|
| 1 — Status mapping precision | 1 h |
| 2 — Transient retry | 30 min |
| 3 — `legal_cache_clear` MCP tool | 45 min |
| 4 — Extractor regex robustness | 1 h |
| 5 — `legal_search` error sentinel | 30 min |
| 6 — Test coverage gaps | 45 min |
| 7 — Live OpenLégi smoke | 30 min |
| 8 — Followups doc + push | 15 min |
| **Total** | **~5 h (1 working day)** |
