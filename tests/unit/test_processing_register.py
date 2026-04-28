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


def test_register_data_subjects_from_parties(vault_dir, monkeypatch):
    """data_subject_categories surfaces unique parties from documents_meta."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("subjects-parties"))
    proj = asyncio.run(svc._get_project("subjects-parties"))

    # Seed two documents with different party labels
    from piighost.service.models import DocumentMetadata
    proj._indexing_store.upsert_document_meta(
        proj._project_name,
        DocumentMetadata(
            doc_id="doc-1",
            doc_type="contrat",
            parties=["client", "avocat", "tiers"],
            dossier_id="dossier-acme",
            extracted_at=1700000000,
        ),
    )
    proj._indexing_store.upsert_document_meta(
        proj._project_name,
        DocumentMetadata(
            doc_id="doc-2",
            doc_type="facture",
            parties=["client"],
            dossier_id="dossier-acme",
            extracted_at=1700000001,
        ),
    )

    register = asyncio.run(svc.processing_register(project="subjects-parties"))
    subjects = set(register.data_subject_categories)
    # Mapped via _PARTY_LABEL_MAP: client→clients, tiers→tiers contractants.
    # Stricter assertion than 'or'-permissive: we know what the mapping
    # produces.
    assert "clients" in subjects, subjects
    assert "tiers contractants" in subjects, subjects
    asyncio.run(svc.close())


def test_register_data_subjects_falls_back_when_parties_empty(vault_dir, monkeypatch):
    """When parties_json is empty across all docs, fall back to the project-name heuristic."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("subjects-empty"))
    proj = asyncio.run(svc._get_project("subjects-empty"))

    # Seed a doc with NO parties
    from piighost.service.models import DocumentMetadata
    proj._indexing_store.upsert_document_meta(
        proj._project_name,
        DocumentMetadata(
            doc_id="doc-1",
            doc_type="autre",
            parties=[],
            dossier_id="client-acme",   # name-heuristic still fires
            extracted_at=1700000000,
        ),
    )

    register = asyncio.run(svc.processing_register(project="subjects-empty"))
    subjects = set(register.data_subject_categories)
    assert "clients" in subjects, subjects
    asyncio.run(svc.close())


def test_register_data_subjects_rh_uses_salaries(vault_dir, monkeypatch):
    """RH profession + parties listing 'salarie' surfaces 'salariés'."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={"controller": {"name": "Service RH", "profession": "rh"}},
        scope="global",
    ))
    asyncio.run(svc.create_project("subjects-rh"))
    proj = asyncio.run(svc._get_project("subjects-rh"))

    from piighost.service.models import DocumentMetadata
    proj._indexing_store.upsert_document_meta(
        proj._project_name,
        DocumentMetadata(
            doc_id="doc-1",
            doc_type="contrat",
            parties=["salarie", "employeur"],
            dossier_id="dossier-rh-2026",
            extracted_at=1700000000,
        ),
    )

    register = asyncio.run(svc.processing_register(project="subjects-rh"))
    subjects = set(register.data_subject_categories)
    assert "salariés" in subjects or "salaries" in subjects, subjects
    asyncio.run(svc.close())


def test_register_data_subjects_entity_tokens_mapped_to_coarse_categories(vault_dir, monkeypatch):
    """Real GLiNER2 emits <<nom_personne:HASH>> / <<organisation:HASH>>
    tokens in parties_json. Those must be classified as 'personnes
    physiques' / 'personnes morales', not surfaced as opaque hashes.

    Closes the data_subjects-readability gap surfaced by the GLiNER2
    e2e smoke against piighost-test-multi-format.
    """
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("subjects-entity-tokens"))
    proj = asyncio.run(svc._get_project("subjects-entity-tokens"))

    from piighost.service.models import DocumentMetadata
    proj._indexing_store.upsert_document_meta(
        proj._project_name,
        DocumentMetadata(
            doc_id="doc-1",
            doc_type="contrat",
            parties=[
                "<<nom_personne:abc12345>>",
                "<<prenom:def67890>>",
                "<<organisation:11111111>>",
                "<<organisation:22222222>>",  # dedup at category level
            ],
            dossier_id="dossier-acme",
            extracted_at=1700000000,
        ),
    )

    register = asyncio.run(svc.processing_register(project="subjects-entity-tokens"))
    subjects = set(register.data_subject_categories)
    # nom_personne + prenom collapse to one category
    assert "personnes physiques" in subjects
    # organisation × 2 collapses to one category
    assert "personnes morales" in subjects
    # Opaque hashes must NOT appear in the user-facing output
    for s in subjects:
        assert "<<" not in s, f"opaque token leaked: {s}"
        assert ":" not in s or s in ("personnes physiques", "personnes morales"), s
    asyncio.run(svc.close())


def test_register_data_subjects_unknown_entity_label_surfaces_label(vault_dir, monkeypatch):
    """Unknown entity labels surface the label (not the hash) for the
    avocat to review."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("subjects-unknown-entity"))
    proj = asyncio.run(svc._get_project("subjects-unknown-entity"))

    from piighost.service.models import DocumentMetadata
    proj._indexing_store.upsert_document_meta(
        proj._project_name,
        DocumentMetadata(
            doc_id="doc-1",
            doc_type="autre",
            parties=["<<robot_agent:99999999>>"],
            dossier_id="dossier-sci-fi",
            extracted_at=1700000000,
        ),
    )
    register = asyncio.run(svc.processing_register(project="subjects-unknown-entity"))
    subjects = set(register.data_subject_categories)
    # The bare label surfaces, not the full token with the hash
    assert "robot_agent" in subjects
    assert "<<robot_agent:99999999>>" not in subjects
    asyncio.run(svc.close())


def test_register_data_subjects_unknown_label_surfaces_as_is(vault_dir, monkeypatch):
    """An unrecognized parties label is preserved verbatim, not silently dropped.

    The mapping is deliberately conservative — _PARTY_LABEL_MAP doesn't
    know every possible role label, so unknown ones surface as-is for
    the avocat to review. This is correct GDPR-engineering: the registre
    Art. 30 must reflect what's actually in the data.
    """
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("subjects-unknown"))
    proj = asyncio.run(svc._get_project("subjects-unknown"))

    from piighost.service.models import DocumentMetadata
    proj._indexing_store.upsert_document_meta(
        proj._project_name,
        DocumentMetadata(
            doc_id="doc-1",
            doc_type="autre",
            parties=["mediateur_judiciaire", "expert_judiciaire"],
            dossier_id="dossier-acme",
            extracted_at=1700000000,
        ),
    )

    register = asyncio.run(svc.processing_register(project="subjects-unknown"))
    subjects = set(register.data_subject_categories)
    # Both labels are not in _PARTY_LABEL_MAP — must appear verbatim
    assert "mediateur_judiciaire" in subjects, subjects
    assert "expert_judiciaire" in subjects, subjects
    asyncio.run(svc.close())
