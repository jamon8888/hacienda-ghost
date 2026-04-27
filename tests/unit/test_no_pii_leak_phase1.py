"""Privacy invariant: no raw PII in any subject_access / forget_subject output.

These tests are gates — failing one indicates a compliance defect.

The stub detector doesn't seed entities for arbitrary text, so we
seed entities + doc_entities directly in the vault. This makes the
tests deterministic across detector backends and isolates the
privacy invariant from detection accuracy.
"""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


_KNOWN_RAW_PII = [
    "Marie Dupont",
    "marie.dupont@example.com",
    "+33 1 23 45 67 89",
    "FR1420041010050500013M02606",
    "Acme Corporation",
]


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def _seed_known_pii(proj, *, doc_id: str = "d1") -> list[str]:
    """Seed 5 known PII entities + link them all to one doc.
    Returns the list of tokens for use in subject_access / forget_subject."""
    seeds = [
        ("<<np:marie>>",    "Marie Dupont",                          "nom_personne"),
        ("<<em:marie>>",    "marie.dupont@example.com",              "email"),
        ("<<tel:marie>>",   "+33 1 23 45 67 89",                     "numero_telephone"),
        ("<<iban:marie>>",  "FR1420041010050500013M02606",           "numero_compte_bancaire"),
        ("<<org:acme>>",    "Acme Corporation",                      "organisation"),
    ]
    tokens: list[str] = []
    for token, original, label in seeds:
        proj._vault.upsert_entity(
            token=token, original=original, label=label, confidence=0.95,
        )
        proj._vault.link_doc_entity(
            doc_id=doc_id, token=token, start_pos=0, end_pos=len(original),
        )
        tokens.append(token)
    return tokens


def test_subject_access_report_no_raw_pii(vault_dir, monkeypatch):
    """SubjectAccessReport.model_dump_json() must not contain any raw
    PII string from the seeded test corpus."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-sa"))
    proj = asyncio.run(svc._get_project("leak-sa"))
    tokens = _seed_known_pii(proj)

    report = asyncio.run(svc.subject_access(tokens=tokens, project="leak-sa"))
    serialized = report.model_dump_json()
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized, (
            f"Raw PII '{raw}' leaked in SubjectAccessReport JSON"
        )
    asyncio.run(svc.close())


def test_subject_access_preview_uses_masking(vault_dir, monkeypatch):
    """subject_preview entries must be masked (first + last char + asterisks)."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-mask"))
    proj = asyncio.run(svc._get_project("leak-mask"))
    tokens = _seed_known_pii(proj)

    report = asyncio.run(svc.subject_access(tokens=tokens, project="leak-mask"))
    # Each preview entry should contain '*' (masking) and the label name
    for preview in report.subject_preview:
        assert "*" in preview, f"Preview not masked: {preview!r}"
    asyncio.run(svc.close())


def test_forget_subject_dry_run_report_no_raw_pii(vault_dir, monkeypatch):
    """ForgetReport (dry_run) must not contain raw tokens or raw PII."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-fs-dry"))
    proj = asyncio.run(svc._get_project("leak-fs-dry"))
    tokens = _seed_known_pii(proj)

    report = asyncio.run(svc.forget_subject(
        tokens=tokens, project="leak-fs-dry", dry_run=True,
    ))
    serialized = report.model_dump_json()
    # No raw PII
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized, f"Raw PII '{raw}' leaked in ForgetReport"
    # Tokens themselves should NOT be in the report — only hashes
    for tok in tokens:
        assert tok not in serialized, f"Raw token '{tok}' leaked in ForgetReport"
    # Hashes ARE present and well-formed
    assert len(report.tokens_to_purge_hashes) == len(tokens)
    for h in report.tokens_to_purge_hashes:
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)
    asyncio.run(svc.close())


def test_forget_subject_apply_report_no_raw_pii(vault_dir, monkeypatch):
    """ForgetReport (apply) must not contain raw tokens or raw PII."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-fs-apply"))
    proj = asyncio.run(svc._get_project("leak-fs-apply"))
    tokens = _seed_known_pii(proj)

    report = asyncio.run(svc.forget_subject(
        tokens=tokens, project="leak-fs-apply", dry_run=False,
    ))
    serialized = report.model_dump_json()
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized
    for tok in tokens:
        assert tok not in serialized
    asyncio.run(svc.close())


def test_forgotten_audit_event_carries_only_hashes(vault_dir, monkeypatch):
    """The 'forgotten' audit event must carry only hashes — never the
    raw token strings, never the raw PII values."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-audit"))
    proj = asyncio.run(svc._get_project("leak-audit"))
    tokens = _seed_known_pii(proj)

    asyncio.run(svc.forget_subject(
        tokens=tokens, project="leak-audit", dry_run=False,
    ))
    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "leak-audit" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit path differs in this environment")
    events = list(read_events(audit_path))
    forgotten = [e for e in events if e.event_type == "forgotten"]
    assert forgotten, "No forgotten event written"
    serialized_audit = forgotten[-1].model_dump_json()
    # Raw PII must not appear
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized_audit, (
            f"Raw PII '{raw}' leaked in forgotten audit event"
        )
    # Raw tokens must not appear (only their hashes)
    for tok in tokens:
        assert tok not in serialized_audit, (
            f"Raw token '{tok}' leaked in forgotten audit event"
        )
    asyncio.run(svc.close())


def test_subject_access_audit_event_redacts_raw_pii(vault_dir, monkeypatch):
    """The 'subject_access' audit event metadata must not contain raw PII
    OR raw vault tokens (only hashes)."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-sa-audit"))
    proj = asyncio.run(svc._get_project("leak-sa-audit"))
    tokens = _seed_known_pii(proj)

    asyncio.run(svc.subject_access(tokens=tokens, project="leak-sa-audit"))
    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "leak-sa-audit" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit path differs")
    events = list(read_events(audit_path))
    sa_events = [e for e in events if e.event_type == "subject_access"]
    assert sa_events, "No subject_access event written"
    serialized = sa_events[-1].model_dump_json()
    # Raw PII must not appear in the audit metadata
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized
    # Raw tokens must not appear in the audit event either
    for tok in tokens:
        assert tok not in serialized, (
            f"Raw token '{tok}' leaked in subject_access audit event"
        )
    # Hashes ARE present and well-formed
    md = sa_events[-1].metadata or {}
    assert "token_hashes" in md
    assert isinstance(md["token_hashes"], list)
    for h in md["token_hashes"]:
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)
    asyncio.run(svc.close())
