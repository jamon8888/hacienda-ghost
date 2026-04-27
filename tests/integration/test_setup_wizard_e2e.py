"""End-to-end test simulating the /hacienda:setup wizard flow at the
service level (no daemon spin-up).

Mirrors the 6-step skill workflow: pick profession -> pre-fill via
defaults -> user-edits-on-top -> set -> get round-trip.
"""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
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


def test_wizard_avocat_global_flow(vault_dir, monkeypatch):
    """Simulate Step 1-6 of the wizard for an avocat, write global, read back."""
    svc = _svc(vault_dir, monkeypatch)

    # Step 1 — profession + load defaults
    defaults = asyncio.run(svc.controller_profile_defaults(profession="avocat"))
    assert defaults["controller"]["profession"] == "avocat"

    # Steps 2-6 — user fills in identity, accepts defaults
    profile = {
        "controller": {
            "name": "Cabinet Dupont & Associés",
            "profession": "avocat",
            "address": "12 rue de la Paix, 75002 Paris",
            "country": "FR",
            "bar_or_order_number": "Barreau de Paris #12345",
        },
        "dpo": {"name": "Marie Dupont", "email": "dpo@dupont-avocats.fr"},
        "defaults": {
            "finalites": defaults["defaults"]["finalites"],
            "bases_legales": defaults["defaults"]["bases_legales"],
            "duree_conservation_apres_fin_mission":
                defaults["defaults"]["duree_conservation_apres_fin_mission"],
        },
    }

    asyncio.run(svc.controller_profile_set(profile=profile, scope="global"))

    # Round-trip
    loaded = asyncio.run(svc.controller_profile_get(scope="global"))
    assert loaded["controller"]["name"] == "Cabinet Dupont & Associés"
    assert loaded["controller"]["bar_or_order_number"] == "Barreau de Paris #12345"
    assert loaded["dpo"]["email"] == "dpo@dupont-avocats.fr"
    assert "Conseil et représentation juridique" in loaded["defaults"]["finalites"]

    asyncio.run(svc.close())


def test_wizard_per_project_override_flow(vault_dir, monkeypatch):
    """Simulate /hacienda:setup --project flow: global stays, project override layers."""
    svc = _svc(vault_dir, monkeypatch)

    # Pre-existing global (set by a prior wizard run)
    global_profile = {
        "controller": {
            "name": "Cabinet Generic",
            "profession": "avocat",
            "country": "FR",
        },
        "defaults": {"finalites": ["Conseil juridique"]},
    }
    asyncio.run(svc.controller_profile_set(profile=global_profile, scope="global"))

    # Create the project the override targets
    asyncio.run(svc.create_project("dossier-acme"))

    # Per-project override — only the DPO field differs for this dossier
    override = {"dpo": {"name": "DPO Spécifique Acme", "email": "dpo@acme.fr"}}
    asyncio.run(svc.controller_profile_set(
        profile=override, scope="project", project="dossier-acme",
    ))

    # The merged read returns global + override
    merged = asyncio.run(svc.controller_profile_get(
        scope="project", project="dossier-acme",
    ))
    assert merged["controller"]["name"] == "Cabinet Generic"  # from global
    assert merged["dpo"]["email"] == "dpo@acme.fr"  # from override

    asyncio.run(svc.close())


def test_wizard_unknown_profession_falls_back(vault_dir, monkeypatch):
    """If the user picks 'autre', defaults() returns empty — wizard uses generic."""
    svc = _svc(vault_dir, monkeypatch)

    autre_defaults = asyncio.run(svc.controller_profile_defaults(profession="autre"))
    assert autre_defaults == {}

    generic_defaults = asyncio.run(svc.controller_profile_defaults(profession="generic"))
    assert generic_defaults["controller"]["profession"] == "generic"

    asyncio.run(svc.close())
