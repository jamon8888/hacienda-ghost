"""Integration test: PIIGhostService.index_path populates documents_meta."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir))


def test_index_populates_documents_meta(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    # Cabinet root contains the client_acme sub-folder (dossier).
    # Indexing the cabinet root means root=tmp_path, so the first
    # sub-folder "client_acme" becomes the dossier_id.
    cabinet = tmp_path / "cabinet"
    cabinet.mkdir()
    dossier = cabinet / "client_acme"
    dossier.mkdir()
    (dossier / "contract_2026.txt").write_text(
        "Article 1 - Le présent contrat est conclu le 2026-04-15.\n"
        "Carol Martin chez Acme Corp.\n",
        encoding="utf-8",
    )

    asyncio.run(svc.index_path(cabinet, project="test-meta"))

    proj = asyncio.run(svc._get_project("test-meta", auto_create=False))
    metas = proj._indexing_store.list_documents_meta("test-meta")
    assert len(metas) == 1
    m = metas[0]
    assert m.doc_type == "contrat"  # filename "contract_2026.txt" matches
    assert m.dossier_id == "client_acme"
    assert m.doc_format == ""  # plain text — kreuzberg not invoked
    asyncio.run(svc.close())


def test_index_path_doesnt_fail_when_metadata_extraction_fails(vault_dir, monkeypatch, tmp_path):
    """If metadata pipeline raises, index_path still completes."""
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client_charlie"
    folder.mkdir()
    # Create a binary garbage file that kreuzberg will fail on
    (folder / "broken.pdf").write_bytes(b"\x00\x01\x02\x03 not a pdf")
    (folder / "good.txt").write_text("Hello, normal text.", encoding="utf-8")

    report = asyncio.run(svc.index_path(folder, project="test-meta-err"))
    # At least good.txt should succeed
    assert report.indexed + report.unchanged + report.modified >= 1
    asyncio.run(svc.close())


def test_index_populates_meta_for_multiple_subfolders(vault_dir, monkeypatch, tmp_path):
    """Every file in every sub-folder gets its dossier_id correctly."""
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "cabinet"
    (folder / "client1").mkdir(parents=True)
    (folder / "client2").mkdir()
    (folder / "client1" / "note1.txt").write_text("Hello A", encoding="utf-8")
    (folder / "client2" / "note2.txt").write_text("Hello B", encoding="utf-8")

    asyncio.run(svc.index_path(folder, project="multi-dossier"))
    proj = asyncio.run(svc._get_project("multi-dossier", auto_create=False))
    metas = proj._indexing_store.list_documents_meta("multi-dossier")
    by_dossier = {m.dossier_id: m for m in metas}
    assert "client1" in by_dossier
    assert "client2" in by_dossier
    asyncio.run(svc.close())
