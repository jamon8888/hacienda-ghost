import asyncio
import os
import pytest
from pathlib import Path
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def test_index_path_single_txt_file(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    vault_dir.mkdir(parents=True, exist_ok=True)
    f = vault_dir / "doc.txt"
    f.write_text("Alice lives in Paris. She works at ACME Corp.")
    report = asyncio.run(svc.index_path(f))
    assert report.indexed == 1
    assert report.skipped == 0
    assert report.errors == []
    asyncio.run(svc.close())


def test_index_path_skips_unsupported_extension(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    vault_dir.mkdir(parents=True, exist_ok=True)
    f = vault_dir / "image.png"
    f.write_bytes(b"\x89PNG\r\n")
    report = asyncio.run(svc.index_path(f))
    assert report.indexed == 0
    asyncio.run(svc.close())


def test_index_path_directory(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    docs = vault_dir / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "a.txt").write_text("Bob is a lawyer in Berlin.")
    (docs / "b.txt").write_text("Carol works at EU Commission.")
    report = asyncio.run(svc.index_path(docs))
    assert report.indexed == 2
    asyncio.run(svc.close())
