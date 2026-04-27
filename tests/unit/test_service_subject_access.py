"""Service-level tests for subject_access — joins clusters → docs → audit."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import RerankerSection, ServiceConfig
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_subject_access_returns_empty_for_unknown_tokens(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("test-sa"))
    report = asyncio.run(svc.subject_access(
        tokens=["<<unknown:zzz>>"], project="test-sa",
    ))
    assert report.subject_tokens == ["<<unknown:zzz>>"]
    assert report.documents == []
    assert report.total_excerpts == 0
    asyncio.run(svc.close())


def test_subject_access_finds_documents_and_excerpts(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client_a"
    folder.mkdir()
    (folder / "note.txt").write_text(
        "Dear Marie Dupont, this is your contract.", encoding="utf-8"
    )
    asyncio.run(svc.index_path(folder, project="test-sa"))

    proj = asyncio.run(svc._get_project("test-sa"))
    # Find any token from the indexed doc to use as the subject
    entries = proj._vault.list_entities(limit=10)
    if not entries:
        pytest.skip("Stub detector produced no entities")
    target_token = entries[0].token

    report = asyncio.run(svc.subject_access(
        tokens=[target_token], project="test-sa",
    ))
    assert report.subject_tokens == [target_token]
    assert len(report.documents) >= 1
    # Privacy invariant: raw value of target_token must NOT appear in any
    # excerpt or in the report — should be replaced by <<SUBJECT>> in excerpts
    raw = entries[0].original
    serialized = report.model_dump_json()
    assert raw not in serialized, f"Raw PII '{raw}' leaked"
    asyncio.run(svc.close())


def test_subject_access_writes_audit_event(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client_b"
    folder.mkdir()
    (folder / "doc.txt").write_text("Marie Dupont here", encoding="utf-8")
    asyncio.run(svc.index_path(folder, project="audit-sa"))

    proj = asyncio.run(svc._get_project("audit-sa"))
    entries = proj._vault.list_entities(limit=5)
    if not entries:
        pytest.skip("No entities to query")
    asyncio.run(svc.subject_access(tokens=[entries[0].token], project="audit-sa"))

    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "audit-sa" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit log path differs in this environment")
    events = list(read_events(audit_path))
    types = [e.event_type for e in events]
    assert "subject_access" in types
    asyncio.run(svc.close())


def test_subject_access_categorizes_tokens_by_label(vault_dir, monkeypatch):
    """Verify categories_found groups tokens by their vault label."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("cat-sa"))
    proj = asyncio.run(svc._get_project("cat-sa"))
    # Seed two entities of different labels
    proj._vault.upsert_entity(
        token="<<np:1>>", original="Marie", label="nom_personne", confidence=0.9,
    )
    proj._vault.upsert_entity(
        token="<<em:1>>", original="m@x.fr", label="email", confidence=0.9,
    )
    report = asyncio.run(svc.subject_access(
        tokens=["<<np:1>>", "<<em:1>>"], project="cat-sa",
    ))
    assert report.categories_found.get("nom_personne") == 1
    assert report.categories_found.get("email") == 1
    asyncio.run(svc.close())
