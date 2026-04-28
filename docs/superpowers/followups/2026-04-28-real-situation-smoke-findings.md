# Real-Situation Smoke Test — Findings

**Date:** 2026-04-28
**Source:** End-to-end smoke test driving every plugin skill workflow against a live daemon process via real HTTP `/rpc`. Setup: spawned `python -m piighost.daemon`, walked through `/hacienda:setup` → index 3 French legal/medical fixtures → `/hacienda:rgpd:registre` → `/hacienda:rgpd:dpia` → render → audit → `cluster_subjects`/`subject_access`/`forget_subject(dry_run)`.

This is the first time the full RGPD subsystem has been exercised end-to-end through an actual long-running daemon process (not `TestClient` in-process). Phase 6 Task 5's MCP-shim integration tests cover the dispatch boundary, but a real subprocess + uvicorn + lifespan + handshake had never been driven.

Severity legend:

- 🔴 **CRITICAL** — blocks fresh-install usability
- 🟡 **IMPORTANT** — fix in next maintenance round
- 🟢 **NICE-TO-HAVE**

---

## ✅ What works end-to-end

Every architectural layer was exercised and passed:

| Layer | Verified |
|---|---|
| Daemon spawn + handshake JSON write | ✓ |
| Bearer-token auth on `/rpc` (401 enforced) | ✓ |
| `/health` endpoint | ✓ |
| All 13+ MCP RPC methods reachable through real HTTP | ✓ |
| `controller_profile_set` / `_get` round-trip via `~/.piighost/controller.toml` | ✓ |
| `controller_profile_defaults("avocat")` returns the bundled TOML | ✓ |
| `index_path` persists to `documents_meta` (when deps available) | ✓ |
| `processing_register` reads vault stats + documents_meta | ✓ |
| `dpia_screening` emits triggers + verdict | ✓ |
| `render_compliance_doc` writes MD to `~/.piighost/exports/` | ✓ |
| Profession-specific Jinja2 templates (avocat preamble + generic include) | ✓ |
| Audit log writes (`registre_generated`, `dpia_screened`) | ✓ |
| Privacy invariant on rendered MD: no raw PII strings present | ✓ |
| `folder_status` for unindexed folders returns `state: empty` | ✓ |

---

## ✅ 1. (RESOLVED on retest) `lancedb` ModuleNotFoundError — dev venv, not manifest

**Original suspicion:** `pip install piighost` couldn't index because `lancedb` was missing from base deps.

**Actual root cause:** the **dev venv** used to run the smoke was incomplete (set up for tests-only, not a full `pip install -e .`). `pyproject.toml` lines 53-57 already declare `lancedb`, `pyarrow`, `rank-bm25`, `sentence-transformers` as **base dependencies** — a real `pip install piighost` would have brought them in.

**Verified on retest:** `pip install lancedb` into the dev venv → re-spawn daemon → all 3 fixtures index cleanly with `indexed: 3, errors: []`.

**Action:** none needed for the manifest. Worth a `tools/dev-bootstrap.sh` script or README note that says "use `uv sync` or `pip install -e .` for the full stack — `pip install pytest` alone won't index."

---

## ✅ 2. (RESOLVED on retest) `dateutil` ModuleNotFoundError — same as #1

**Original suspicion:** `python-dateutil` not in deps.

**Actual root cause:** `python-dateutil` IS in `uv.lock` (transitively via kreuzberg) — verified by grep. The dev venv just didn't have it installed.

**Verified on retest:** `pip install python-dateutil` (force-reinstall to clear the corrupted `~iighost` ghost metadata in the venv) → re-spawn daemon → medical document with French date "né le 12 mars 1975" + French SSN indexes cleanly.

**Action:** none needed.

---

## 🟢 1b. Dev-venv corruption: phantom `~iighost` distribution

While running the smoke, pip emitted repeated warnings:

```
WARNING: Ignoring invalid distribution ~iighost (...)
WARNING: Ignoring invalid distribution ~~ighost (...)
```

The `~iighost` / `~~ighost` directories are leftover partial-install artifacts. They cause `pip install` to silently no-op when the package is "already satisfied" but the import path is broken — what tripped up finding #2 (we had to use `--force-reinstall` to actually land `python-dateutil`).

**Fix:** clean the venv with `rm -rf .venv/Lib/site-packages/~iighost*` (Windows) or recreate with `uv sync` / `python -m venv .venv && pip install -e .`. Capture in a `tools/dev-bootstrap.sh` script.

Estimated effort: 5 min.

Recommend the first (just add the dep) — `python-dateutil` is small and ubiquitous.

Estimated effort: 5 min.

---

## 🟡 3. `/shutdown` endpoint sets a flag but doesn't terminate uvicorn cleanly on Windows

**Repro:**
```
curl -X POST http://127.0.0.1:$PORT/shutdown -H "Authorization: Bearer $TOKEN"
# returns {"ok":true}
sleep 5
rm -rf vault/  # fails: "Device or resource busy"
```

**Cause:** `daemon/server.py` has a `shutdown` route that does `shutdown_event.set()` and returns 200, but nothing in the codebase actually awaits that event to send `SIGINT` / call `uvicorn.Server.shutdown()`. So uvicorn keeps the process alive holding SQLite + LanceDB file handles.

**Effect:** On Windows (where files can't be deleted while held open), tests/scripts can't tear down a daemon and re-spawn cleanly without manually killing the PID. Also affects the smoke test harness — currently has to use a fresh vault dir per attempt.

**Fix:** wire the `shutdown_event` into the lifespan or spawn a watcher task that catches the event and calls `os.kill(os.getpid(), signal.SIGINT)`. Alternative: replace the endpoint with a clear "this no-ops on Windows; kill the PID instead" comment if we accept the limitation.

Estimated effort: 1 h including a regression test that spawns/shuts/respawns the daemon in the same vault.

---

## 🟢 4. `index_path` report uses field names that aren't documented anywhere

**File:** `src/piighost/service/models.py` (IndexReport, or whatever the dataclass is called)

The smoke driver guessed `docs_indexed`, `chunks_added`, `entities_extracted`, `failed` — all wrong. Real fields are `indexed`, `modified`, `skipped`, `unchanged`, `deleted`, `errors`, `duration_ms`, `project`. None are documented in the MCP tool description. Anyone calling `index_path` from a script has to read the model definition.

**Fix:** add field-by-field doc comments in `IndexReport`, OR include the schema in the ToolSpec description. The latter is more useful for MCP-driven callers.

Estimated effort: 15 min.

---

## 🟢 5. `index_path` report compresses error messages, hiding root cause

**File:** `src/piighost/service/core.py:365`

The per-file error is captured as `f"{p.name}: {type(exc).__name__}"` — the exception message is stripped. So callers see `"contrat-acme.txt: ModuleNotFoundError"` and have no idea that `lancedb` is the missing module. The full `f"{type(exc).__name__}: {exc}"` is stored in the SQLite `indexed_files.error_message` column but isn't surfaced through the MCP boundary.

**Fix:** include the exception message in the report's `errors` list (truncated to a reasonable length, e.g. 200 chars). Privacy trade-off: exception messages can include filenames / paths which are reasonable to surface; if any indexer codepath ever puts user PII in an exception message, that's a separate bug worth fixing at the source.

Estimated effort: 10 min + a regression test.

---

## 🟢 6. Stub detector is too limited for end-to-end smoke

**File:** `src/piighost/detector/stub.py` (or wherever `PIIGHOST_DETECTOR=stub` resolves to)

The stub recognizes a hardcoded handful of strings (apparently "Paris" + maybe 2-3 others). With realistic French legal/medical text containing names, emails, phone numbers, IBANs, SSNs, dates of birth — none of those are detected. Effect on the smoke: `cluster_subjects("Marie")` returns 0 clusters, so `subject_access` and `forget_subject` paths can't be exercised end-to-end without GLiNER2 + the French LoRA adapter loaded.

**Fix options:**
- Expand the stub to recognize a richer set of French test fixtures (Marie Curie, Pierre Durand, IBAN patterns, French SSN patterns). The point of the stub is to give tests deterministic behavior without ML models — extending its vocabulary is consistent with that purpose.
- Or document that real-situation testing requires `pip install piighost[gliner2]` (which itself needs the cleanup from finding #1).

Recommend the first.

Estimated effort: 1 h + regression tests for each new pattern.

---

## 🟢 7. `folder_status` requires `bootstrap_client_folder` first

**File:** `src/piighost/service/core.py` (folder_status implementation)

The smoke driver called `folder_status(folder=<corpus_dir>)` after `index_path` had already indexed that corpus. Result: `state: empty, total_docs: 0`. Reason: `folder_status` resolves the folder to a project via `resolve_project_for_folder`, but the corpus was indexed under a separately-named project (`dossier-acme-2026`), not via the Cowork bootstrap path.

This is **technically correct** behaviour — `folder_status` is for the Cowork plugin's per-folder integration, not for arbitrary indexed paths. But the discrepancy could surprise a script author. Worth a one-line note in the tool description: "Reflects only folders bootstrapped via `bootstrap_client_folder` or known to the Cowork integration."

Estimated effort: 5 min.

---

## Resolution log

| # | Issue | Status | Resolution |
|---|---|---|---|
| 1 | ~~`lancedb` missing from base deps~~ | resolved | ✅ retest confirmed lancedb is in pyproject; dev venv was incomplete |
| 1b | Dev venv has phantom `~iighost` metadata blocking pip installs | open | 🟢 doc + bootstrap script |
| 2 | ~~`dateutil` missing~~ | resolved | ✅ retest: dateutil in uv.lock, dev venv just lacked it |
| 3 | `/shutdown` doesn't terminate uvicorn | open | 🟡 |
| 4 | IndexReport field names undocumented | open | 🟢 |
| 5 | Error messages compressed at MCP boundary | open | 🟢 |
| 6 | Stub detector too limited for e2e | open | 🟢 |
| 7 | `folder_status` Cowork-only nuance undocumented | open | 🟢 |

**Retest verdict:** with a properly-installed venv (lancedb + dateutil present), the smoke runs **clean — 3/3 fixtures indexed, no errors, every layer green**. The MCP+plugin integration is production-ready for the no-ML-models path. Real GLiNER2 detection (still needed to exercise `subject_access`/`forget_subject` end-to-end) is the only uncovered branch.

---

## Smoke harness

The smoke driver (`_smoke_tmp/drive_smoke.py`) is gitignored as scratch but the pattern is worth preserving as a checked-in integration test for next phase. Sketch:

```python
# tests/integration/test_real_daemon_smoke.py
def test_full_rgpd_workflow_against_real_daemon(tmp_path):
    """Spawn the actual daemon subprocess and walk through every plugin
    skill workflow via real HTTP /rpc. Skipped if lancedb is missing."""
    pytest.importorskip("lancedb")
    pytest.importorskip("dateutil")
    # ... spawn daemon, wait for handshake, walk steps ...
```

This is a Phase 7 candidate.
