"""Privacy invariants for Phase 2 outputs (registre + DPIA + render).

These tests are gates -- failing one indicates a compliance defect.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


_KNOWN_RAW_PII = [
    "Marie Dupont",
    "marie.dupont@example.com",
    "+33 1 23 45 67 89",
    "FR1420041010050500013M02606",
]


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    # Isolate the global controller profile (lives under Path.home()) so
    # tests do not pollute the developer's real ~/.piighost/ and so the
    # render_compliance_doc containment check (Task 5 hardening) accepts
    # output paths under the redirected home.
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


def _seed_pii(proj):
    """Seed 4 known PII entities directly in the vault."""
    seeds = [
        ("<<np:1>>", "Marie Dupont", "nom_personne"),
        ("<<em:1>>", "marie.dupont@example.com", "email"),
        ("<<tel:1>>", "+33 1 23 45 67 89", "numero_telephone"),
        ("<<iban:1>>", "FR1420041010050500013M02606", "numero_compte_bancaire"),
    ]
    for token, original, label in seeds:
        proj._vault.upsert_entity(
            token=token, original=original, label=label, confidence=0.9,
        )


def test_processing_register_no_raw_pii(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-reg"))
    proj = asyncio.run(svc._get_project("leak-reg"))
    _seed_pii(proj)
    register = asyncio.run(svc.processing_register(project="leak-reg"))
    serialized = register.model_dump_json()
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized, (
            f"Raw PII '{raw}' leaked in ProcessingRegister"
        )
    asyncio.run(svc.close())


def test_dpia_screening_no_raw_pii(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-dpia"))
    proj = asyncio.run(svc._get_project("leak-dpia"))
    _seed_pii(proj)
    dpia = asyncio.run(svc.dpia_screening(project="leak-dpia"))
    serialized = dpia.model_dump_json()
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized, (
            f"Raw PII '{raw}' leaked in DPIAScreening"
        )
    asyncio.run(svc.close())


def test_rendered_md_no_raw_pii(vault_dir, monkeypatch):
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("leak-render"))
    proj = asyncio.run(svc._get_project("leak-render"))
    _seed_pii(proj)
    register = asyncio.run(svc.processing_register(project="leak-render"))
    # Output must live under the (monkeypatched) ~/.piighost/ to satisfy
    # the Task 5 containment check in render_compliance_doc.
    out_dir = Path.home() / ".piighost" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "registre.md"
    asyncio.run(svc.render_compliance_doc(
        data=register.model_dump(), format="md", profile="generic",
        output_path=str(out),
    ))
    rendered = out.read_text(encoding="utf-8")
    for raw in _KNOWN_RAW_PII:
        assert raw not in rendered, (
            f"Raw PII '{raw}' leaked in rendered MD output"
        )
    asyncio.run(svc.close())
