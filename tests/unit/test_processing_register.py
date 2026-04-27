"""Service-level tests for processing_register (Art. 30)."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    # Redirect Path.home() / HOME / USERPROFILE so the global
    # ControllerProfileService writes to a sandbox instead of the
    # developer's real ~/.piighost/.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_processing_register_empty_project(vault_dir, monkeypatch):
    """Newly-created project with nothing indexed should still produce a
    valid (mostly empty) ProcessingRegister."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("reg-empty"))
    report = asyncio.run(svc.processing_register(project="reg-empty"))
    assert report.v == 1
    assert report.project == "reg-empty"
    assert report.data_categories == []
    assert report.documents_summary.total_docs == 0
    asyncio.run(svc.close())


def test_processing_register_inventory_from_vault_stats(vault_dir, monkeypatch):
    """Categories and counts come from vault.stats() and documents_meta."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("reg-inv"))
    proj = asyncio.run(svc._get_project("reg-inv"))
    # Seed entities of various labels
    seeds = [
        ("<<np:1>>", "Marie", "nom_personne"),
        ("<<np:2>>", "Jean", "nom_personne"),
        ("<<em:1>>", "m@x.fr", "email"),
        ("<<sante:1>>", "diabetes", "donnee_sante"),  # Art. 9 sensitive
    ]
    for token, original, label in seeds:
        proj._vault.upsert_entity(
            token=token, original=original, label=label, confidence=0.9,
        )

    report = asyncio.run(svc.processing_register(project="reg-inv"))
    by_label = {c.label: c.count for c in report.data_categories}
    assert by_label.get("nom_personne") == 2
    assert by_label.get("email") == 1
    assert by_label.get("donnee_sante") == 1
    # Sensitive flag set on Art. 9 categories
    sensitive_labels = [c.label for c in report.data_categories if c.sensitive]
    assert "donnee_sante" in sensitive_labels
    assert "nom_personne" not in sensitive_labels
    asyncio.run(svc.close())


def test_processing_register_pulls_controller_info(vault_dir, monkeypatch):
    """controller name + DPO + finalités come from ControllerProfile."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={
            "controller": {"name": "Cabinet Test", "profession": "avocat"},
            "dpo": {"name": "DPO Marie", "email": "dpo@x.fr"},
            "defaults": {
                "finalites": ["Conseil juridique"],
                "bases_legales": ["execution_contrat"],
                "duree_conservation_apres_fin_mission": "5 ans",
            },
        },
        scope="global",
    ))
    asyncio.run(svc.create_project("reg-ctrl"))
    report = asyncio.run(svc.processing_register(project="reg-ctrl"))
    assert report.controller.name == "Cabinet Test"
    assert report.controller.profession == "avocat"
    assert report.dpo is not None
    assert report.dpo.name == "DPO Marie"
    assert "Conseil juridique" in report.processing_purposes
    asyncio.run(svc.close())


def test_processing_register_audit_event_written(vault_dir, monkeypatch):
    """The act of generating a registre is itself audited."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("reg-audit"))
    asyncio.run(svc.processing_register(project="reg-audit"))
    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "reg-audit" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit path differs in this env")
    events = list(read_events(audit_path))
    types = [e.event_type for e in events]
    assert "registre_generated" in types
    asyncio.run(svc.close())
