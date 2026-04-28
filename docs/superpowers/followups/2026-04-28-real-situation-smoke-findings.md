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

## 🔴 1. `pip install piighost` (no extras) cannot index — `lancedb` missing

**Repro:** fresh venv, `pip install -e .`, `python -m piighost.daemon --vault ...`, then call `index_path`. Every file fails with:

```
ModuleNotFoundError: No module named 'lancedb'
```

**Root cause:** commit `86e247e` ("ship full stack by default") restructured `[project.optional-dependencies]` so the `[index]` extra became an empty alias and its packages moved to base dependencies. But `lancedb` is NOT in the current base `[project.dependencies]` — it was lost in that migration.

**Effect:** Anyone who follows the README install path (`pip install piighost`) cannot index a single document. The MCP daemon starts, the RGPD tools work for empty projects (registre with `documents.total: 0`, DPIA verdict `dpia_not_required`), but the actual workflow requires `pip install lancedb` separately.

**Fix:** add `lancedb`, `pyarrow`, and `rank-bm25` (and probably `sentence-transformers`) to `[project.dependencies]` in `pyproject.toml`. Verify with:

```bash
python -m venv /tmp/v && source /tmp/v/bin/activate
pip install -e .
python -m piighost.daemon --vault /tmp/vault &
# wait for handshake
curl -X POST http://127.0.0.1:$PORT/rpc \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"method":"index_path","params":{"path":"/tmp/sample.txt","project":"default"}}'
# expect indexed: 1, no errors
```

Estimated effort: 30 min (deps + verify on a clean venv).

---

## 🟡 2. `dateutil` missing for date-parsing in metadata extractor

**Repro:** index a file with a French-format date (e.g. "né le 12 mars 1975" or a French SSN pattern). Fails with:

```
ModuleNotFoundError: No module named 'dateutil'
```

**Effect:** medical / civil-status documents get a per-file index error and aren't persisted to `documents_meta`. The other documents in the same `index_path` call are unaffected.

**Fix options:**
- Add `python-dateutil>=2.9` to `[project.dependencies]`. (~5 min)
- Or guard the import in the date parser with `try/except ImportError` and fall back to the stdlib `datetime.fromisoformat` for ISO-only formats. The bundled medical templates use French dates so the dateutil path is needed for médecin profession.

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
| 1 | `lancedb` missing from base deps | open | 🔴 fix before next release |
| 2 | `dateutil` missing | open | 🟡 fix in next maintenance |
| 3 | `/shutdown` doesn't terminate uvicorn | open | 🟡 |
| 4 | IndexReport field names undocumented | open | 🟢 |
| 5 | Error messages compressed at MCP boundary | open | 🟢 |
| 6 | Stub detector too limited for e2e | open | 🟢 |
| 7 | `folder_status` Cowork-only nuance undocumented | open | 🟢 |

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
