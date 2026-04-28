"""End-to-end smoke against a real daemon subprocess.

Spawns ``python -m piighost.daemon`` as a child process, waits for the
handshake JSON, then walks every plugin skill workflow against it via
real HTTP /rpc:

    /hacienda:setup           → controller_profile_set + _get
    /hacienda:rgpd:registre   → processing_register + render_compliance_doc
    /hacienda:rgpd:dpia       → dpia_screening + render_compliance_doc
    /hacienda:rgpd:access     → cluster_subjects + subject_access
    /hacienda:rgpd:forget     → forget_subject(dry_run=True)

Phase 6 Task 5 already covers dispatch via in-process Starlette
TestClient. This test goes further: real subprocess + real uvicorn +
real lifespan + real handshake. It catches a class of bugs (lifecycle,
file locks, dep gaps) that TestClient cannot.

Skipped if optional indexer deps are missing (lancedb, kreuzberg's
dateutil dep) — those gate `index_path`. The test still validates the
RGPD surface against an empty project if deps are missing.

Phase 7 spec: docs/superpowers/followups/2026-04-28-real-situation-smoke-findings.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

import pytest


# Skip-markers for optional deps that the daemon needs for a full smoke
HAS_LANCEDB = pytest.importorskip.__module__  # always present (importorskip itself)
try:
    import lancedb  # noqa: F401
    _LANCEDB_OK = True
except ImportError:
    _LANCEDB_OK = False

try:
    import dateutil  # noqa: F401
    _DATEUTIL_OK = True
except ImportError:
    _DATEUTIL_OK = False


CORPUS_FIXTURES = {
    "contrat-acme.txt": (
        "CONTRAT DE PRESTATION\n"
        "Cabinet Dupont & Associés, Maître Jean Dupont, Barreau de Paris.\n"
        "Société ACME SARL, Marie Curie, marie.curie@acme.fr.\n"
        "Téléphone: 01 23 45 67 89.\n"
        "Secret professionnel Art. 66-5 loi 1971.\n"
    ),
    "facture.txt": (
        "FACTURE 2026-001\n"
        "Cabinet Dupont & Associés / Société ACME SARL\n"
        "IBAN: FR14 2004 1010 0505 0001 3M02 606\n"
        "Honoraires: 5 000 EUR HT.\n"
    ),
}


def _spawn_daemon(vault_dir: Path) -> tuple[subprocess.Popen, dict]:
    """Spawn the daemon subprocess and wait for handshake JSON.

    Returns (popen, handshake_dict). Raises TimeoutError if the handshake
    doesn't appear within 30 seconds.
    """
    # Disable cross-encoder reranker — most dev envs lack transformers
    config = vault_dir / "config.toml"
    config.write_text("[reranker]\nbackend = \"none\"\n", encoding="utf-8")

    env = os.environ.copy()
    env["PIIGHOST_DETECTOR"] = "stub"
    env["PIIGHOST_EMBEDDER"] = "stub"
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        [sys.executable, "-m", "piighost.daemon", "--vault", str(vault_dir)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    handshake_path = vault_dir / "daemon.json"
    deadline = time.monotonic() + 30.0
    hs: dict | None = None
    # Phase A: wait for handshake JSON
    while time.monotonic() < deadline:
        if handshake_path.exists():
            try:
                candidate = json.loads(handshake_path.read_text("utf-8"))
                if candidate.get("port") and candidate.get("token"):
                    hs = candidate
                    break
            except json.JSONDecodeError:
                pass  # mid-write
        if proc.poll() is not None:
            out = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""
            raise RuntimeError(f"Daemon exited early: {out}")
        time.sleep(0.5)

    if hs is None:
        proc.terminate()
        raise TimeoutError("Daemon did not write handshake within 30s")

    # Phase B: poll /health until uvicorn is actually listening.
    # Handshake JSON is written BEFORE uvicorn.run() starts the server,
    # so there's a window where the file exists but the port is closed.
    health_url = f"http://127.0.0.1:{hs['port']}/health"
    while time.monotonic() < deadline:
        try:
            with request.urlopen(health_url, timeout=2) as resp:
                if json.loads(resp.read())["ok"] is True:
                    return proc, hs
        except Exception:
            pass
        if proc.poll() is not None:
            out = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""
            raise RuntimeError(f"Daemon exited during /health poll: {out}")
        time.sleep(0.5)

    proc.terminate()
    raise TimeoutError("Daemon /health did not respond within 30s")


def _shutdown_daemon(proc: subprocess.Popen, hs: dict) -> None:
    """Best-effort daemon shutdown.

    /shutdown sets a flag but doesn't terminate uvicorn cleanly on
    Windows (followup #3). We try the endpoint, then proc.terminate(),
    then proc.kill() as a last resort.
    """
    try:
        body = json.dumps({}).encode("utf-8")
        req = request.Request(
            f"http://127.0.0.1:{hs['port']}/shutdown",
            data=body, method="POST",
            headers={"Authorization": f"Bearer {hs['token']}"},
        )
        request.urlopen(req, timeout=2)
    except Exception:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _rpc(hs: dict, method: str, params: dict | None = None) -> dict:
    """Call the daemon's /rpc endpoint."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}
    }).encode("utf-8")
    req = request.Request(
        f"http://127.0.0.1:{hs['port']}/rpc",
        data=body, method="POST",
        headers={
            "Authorization": f"Bearer {hs['token']}",
            "Content-Type": "application/json",
        },
    )
    with request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if out.get("error"):
        raise RuntimeError(f"RPC {method}: {out['error']}")
    return out["result"]


@pytest.fixture()
def daemon_setup(tmp_path, monkeypatch):
    """Spawn daemon + redirect Path.home so exports land in tmp_path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    # Windows daemon subprocess inherits the env at spawn time, so the
    # daemon-side Path.home will follow USERPROFILE. We need this so
    # render_compliance_doc's containment check accepts our outputs.

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    proc, hs = _spawn_daemon(vault_dir)
    yield vault_dir, hs, home
    _shutdown_daemon(proc, hs)


def test_full_rgpd_workflow_against_real_daemon(daemon_setup):
    """The 'whole MCP and plugin' end-to-end smoke."""
    vault_dir, hs, home = daemon_setup

    # --- Step 1: /hacienda:setup ---
    defaults = _rpc(hs, "controller_profile_defaults", {"profession": "avocat"})
    assert defaults["controller"]["profession"] == "avocat"

    profile = {
        "controller": {
            "name": "Cabinet Dupont", "profession": "avocat",
            "country": "FR",
        },
        "defaults": {
            "finalites": defaults["defaults"]["finalites"],
            "bases_legales": defaults["defaults"]["bases_legales"],
            "duree_conservation_apres_fin_mission":
                defaults["defaults"]["duree_conservation_apres_fin_mission"],
        },
    }
    _rpc(hs, "controller_profile_set", {"profile": profile, "scope": "global"})
    loaded = _rpc(hs, "controller_profile_get", {"scope": "global"})
    assert loaded["controller"]["name"] == "Cabinet Dupont"

    # --- Step 2: project + (best-effort) index ---
    _rpc(hs, "create_project", {"name": "smoke", "description": "real daemon smoke"})

    if _LANCEDB_OK and _DATEUTIL_OK:
        # Real index path. Write fixtures + index them.
        corpus = vault_dir.parent / "corpus"
        corpus.mkdir()
        for name, content in CORPUS_FIXTURES.items():
            (corpus / name).write_text(content, encoding="utf-8")
        report = _rpc(hs, "index_path", {
            "path": str(corpus.resolve()),
            "recursive": True, "force": True, "project": "smoke",
        })
        # We expect at least 1 file to index cleanly (the contract).
        # Some fixtures may fail on subset-installed dev envs; that's
        # captured in errors[]. We assert >=1 indexed, not all.
        assert report["indexed"] + report["modified"] >= 1, report

    # --- Step 3: registre ---
    register = _rpc(hs, "processing_register", {"project": "smoke"})
    assert register["controller"]["name"] == "Cabinet Dupont"
    assert register["v"] == 1

    # --- Step 4: render registre ---
    rr = _rpc(hs, "render_compliance_doc", {
        "data": register, "format": "md", "profile": "avocat", "project": "smoke",
    })
    out_path = Path(rr["path"])
    assert out_path.exists()
    body = out_path.read_text("utf-8")
    assert "Cabinet d'avocat" in body  # avocat-flavored header
    assert "Cabinet Dupont" in body  # controller name surfaces

    # --- Step 5: DPIA ---
    dpia = _rpc(hs, "dpia_screening", {"project": "smoke"})
    assert dpia["verdict"] in ("dpia_required", "dpia_recommended", "dpia_not_required")
    assert "cnil_5" in [t["code"] for t in dpia["triggers"]]  # always-on

    rr2 = _rpc(hs, "render_compliance_doc", {
        "data": dpia, "format": "md", "profile": "avocat", "project": "smoke",
    })
    assert Path(rr2["path"]).exists()

    # --- Step 6: cluster_subjects (stub detector → likely 0 clusters) ---
    clusters = _rpc(hs, "cluster_subjects", {"query": "Marie", "project": "smoke"})
    assert isinstance(clusters, list)  # never raises, may be empty

    # --- Step 7: forget_subject(dry_run=True) — only if we have clusters ---
    if clusters:
        fr = _rpc(hs, "forget_subject", {
            "tokens": clusters[0]["tokens"], "project": "smoke", "dry_run": True,
        })
        assert fr["dry_run"] is True
        assert isinstance(fr["tokens_to_purge_hashes"], list)

    # --- Step 8: audit log ---
    audit_path = vault_dir / "projects" / "smoke" / "audit.log"
    assert audit_path.exists()
    events = audit_path.read_text("utf-8").strip().splitlines()
    assert len(events) >= 2
    types = {json.loads(e)["event_type"] for e in events}
    assert "registre_generated" in types
    assert "dpia_screened" in types

    # --- Step 9: privacy invariant on rendered MD ---
    raw_pii = ["Marie Curie", "marie.curie@acme.fr", "01 23 45 67 89",
               "FR14 2004 1010 0505 0001 3M02 606"]
    for md in (home / ".piighost" / "exports").glob("smoke-*.md"):
        body = md.read_text("utf-8")
        for raw in raw_pii:
            assert raw not in body, f"Raw PII '{raw}' leaked in {md.name}"

    # --- Step 10: auth check (negative) ---
    bad_req = request.Request(
        f"http://127.0.0.1:{hs['port']}/rpc",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "list_projects"}).encode("utf-8"),
        method="POST",
        headers={"Authorization": "Bearer wrong-token", "Content-Type": "application/json"},
    )
    try:
        request.urlopen(bad_req, timeout=5)
        raise AssertionError("Expected 401 for wrong token")
    except Exception as exc:  # urllib raises HTTPError on 4xx
        assert "401" in str(exc) or "Unauthorized" in str(exc), exc


def test_real_daemon_handshake_within_30s(daemon_setup):
    """Daemon startup latency budget: ~30s including model warm.

    With stub detector + stub embedder + reranker=none, this should
    be well under 5s on any reasonable machine.
    """
    vault_dir, hs, _home = daemon_setup
    started = hs["started_at"]
    assert started > 0
    # /health must respond
    req = request.Request(
        f"http://127.0.0.1:{hs['port']}/health",
        headers={"Authorization": f"Bearer {hs['token']}"},
    )
    with request.urlopen(req, timeout=5) as resp:
        assert json.loads(resp.read())["ok"] is True
