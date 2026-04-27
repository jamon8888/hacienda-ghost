"""Service-level tests for dpia_screening (DPIA-lite Art. 35)."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    # Isolate the global controller profile (lives under Path.home()) so
    # tests do not pollute the developer's real ~/.piighost/.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_dpia_empty_project_verdict_not_required(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("dpia-empty"))
    report = asyncio.run(svc.dpia_screening(project="dpia-empty"))
    assert report.verdict in ("dpia_not_required", "dpia_recommended")
    assert report.cnil_pia_url.startswith("https://www.cnil.fr/")
    asyncio.run(svc.close())


def test_dpia_required_when_sensitive_data_at_scale(vault_dir, monkeypatch):
    """>=1 mandatory trigger (Art. 35.3.b) when sensitive data > 100 entries."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("dpia-sens"))
    proj = asyncio.run(svc._get_project("dpia-sens"))
    # Seed 150 sensitive entities
    for i in range(150):
        proj._vault.upsert_entity(
            token=f"<<sante:{i}>>", original=f"diabete-{i}",
            label="donnee_sante", confidence=0.9,
        )
    report = asyncio.run(svc.dpia_screening(project="dpia-sens"))
    assert report.verdict == "dpia_required"
    trigger_codes = [t.code for t in report.triggers]
    assert "art35.3.b" in trigger_codes
    asyncio.run(svc.close())


def test_dpia_innovative_use_always_present(vault_dir, monkeypatch):
    """Trigger cnil_5 (usage innovant -- IA/NER) is always emitted because
    piighost itself uses ML for detection."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("dpia-ai"))
    report = asyncio.run(svc.dpia_screening(project="dpia-ai"))
    trigger_codes = [t.code for t in report.triggers]
    assert "cnil_5" in trigger_codes
    asyncio.run(svc.close())


def test_dpia_emits_pia_inputs(vault_dir, monkeypatch):
    """The cnil_pia_inputs block must be populated for direct import into
    the CNIL PIA software."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={
            "controller": {"name": "Test Cabinet", "profession": "avocat"},
            "defaults": {
                "finalites": ["Conseil juridique"],
                "bases_legales": ["execution_contrat"],
            },
        },
        scope="global",
    ))
    asyncio.run(svc.create_project("dpia-inputs"))
    report = asyncio.run(svc.dpia_screening(project="dpia-inputs"))
    assert report.cnil_pia_inputs.processing_name
    assert "Conseil juridique" in report.cnil_pia_inputs.purposes
    asyncio.run(svc.close())


def test_dpia_audit_event_written(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("dpia-audit"))
    asyncio.run(svc.dpia_screening(project="dpia-audit"))
    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "dpia-audit" / "audit.log"
    assert audit_path.exists(), f"expected audit log at {audit_path}"
    events = list(read_events(audit_path))
    types = [e.event_type for e in events]
    assert "dpia_screened" in types
    asyncio.run(svc.close())
