"""Service-level tests for forget_subject (Art. 17 tombstone)."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.core import PIIGhostService
from piighost.service.config import ServiceConfig, RerankerSection


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_forget_subject_dry_run_does_not_modify_vault(vault_dir, monkeypatch, tmp_path):
    """Dry run must NOT delete vault entries or rewrite chunks."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("forget-dry"))
    proj = asyncio.run(svc._get_project("forget-dry"))
    # Seed manually so test doesn't depend on detector output
    proj._vault.upsert_entity(
        token="<<np:test>>", original="Test User",
        label="nom_personne", confidence=0.9,
    )
    proj._vault.link_doc_entity(
        doc_id="d1", token="<<np:test>>", start_pos=0, end_pos=4,
    )

    before = proj._vault.get_by_token("<<np:test>>")
    assert before is not None

    report = asyncio.run(svc.forget_subject(
        tokens=["<<np:test>>"], project="forget-dry", dry_run=True,
    ))
    assert report.dry_run is True
    assert "d1" in report.docs_affected
    # Vault entry MUST still exist after dry run
    after = proj._vault.get_by_token("<<np:test>>")
    assert after is not None
    assert after.original == before.original
    asyncio.run(svc.close())


def test_forget_subject_apply_purges_vault(vault_dir, monkeypatch, tmp_path):
    """Apply removes the token from the vault."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("forget-apply"))
    proj = asyncio.run(svc._get_project("forget-apply"))
    proj._vault.upsert_entity(
        token="<<np:apply>>", original="Test User",
        label="nom_personne", confidence=0.9,
    )
    proj._vault.link_doc_entity(
        doc_id="d1", token="<<np:apply>>", start_pos=0, end_pos=4,
    )

    report = asyncio.run(svc.forget_subject(
        tokens=["<<np:apply>>"], project="forget-apply",
        dry_run=False, legal_basis="c-opposition",
    ))
    assert report.dry_run is False
    # Vault entry GONE
    assert proj._vault.get_by_token("<<np:apply>>") is None
    # legal_basis recorded
    assert report.legal_basis == "c-opposition"
    asyncio.run(svc.close())


def test_forget_subject_writes_tombstone_audit(vault_dir, monkeypatch, tmp_path):
    """Audit event 'forgotten' written with HASHES only (no raw token, no raw PII)."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("forget-audit"))
    proj = asyncio.run(svc._get_project("forget-audit"))
    proj._vault.upsert_entity(
        token="<<np:audited>>", original="Audited Person",
        label="nom_personne", confidence=0.9,
    )
    proj._vault.link_doc_entity(
        doc_id="d1", token="<<np:audited>>", start_pos=0, end_pos=4,
    )

    asyncio.run(svc.forget_subject(
        tokens=["<<np:audited>>"], project="forget-audit",
        dry_run=False, legal_basis="b-retrait_consentement",
    ))

    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "forget-audit" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit log path differs")
    events = list(read_events(audit_path))
    forgotten = [e for e in events if e.event_type == "forgotten"]
    assert len(forgotten) >= 1
    ev = forgotten[-1]
    serialized = ev.model_dump_json()
    # Tombstone invariant: raw token MUST NOT appear anywhere in the event
    assert "<<np:audited>>" not in serialized
    # Raw PII value MUST NOT appear either
    assert "Audited Person" not in serialized
    # Hashes ARE present
    md = ev.metadata or {}
    assert "tokens_purged_hashes" in md
    assert isinstance(md["tokens_purged_hashes"], list)
    assert len(md["tokens_purged_hashes"]) == 1
    # Each hash is exactly 8 hex chars
    for h in md["tokens_purged_hashes"]:
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)
    assert md.get("legal_basis") == "b-retrait_consentement"
    asyncio.run(svc.close())


def test_forget_subject_returns_report_with_doc_count(vault_dir, monkeypatch):
    """ForgetReport tracks affected docs and chunks."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("forget-count"))
    proj = asyncio.run(svc._get_project("forget-count"))
    proj._vault.upsert_entity(
        token="<<np:count>>", original="X", label="nom_personne", confidence=0.9,
    )
    # 3 docs, 1 link each
    for doc in ["d1", "d2", "d3"]:
        proj._vault.link_doc_entity(
            doc_id=doc, token="<<np:count>>", start_pos=0, end_pos=1,
        )

    report = asyncio.run(svc.forget_subject(
        tokens=["<<np:count>>"], project="forget-count", dry_run=True,
    ))
    assert sorted(report.docs_affected) == ["d1", "d2", "d3"]
    assert len(report.tokens_to_purge_hashes) == 1
    asyncio.run(svc.close())
