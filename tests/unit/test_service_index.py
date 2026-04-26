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


def test_duplicate_content_at_two_paths_indexes_both(vault_dir, monkeypatch):
    """Regression: client1/foo.txt and client2/foo.txt with IDENTICAL
    content must both end up in vault.indexed_files. Earlier behavior
    keyed by content_hash → second write overwrote first via ON
    CONFLICT(doc_id), losing one of the two file_paths."""
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    base = vault_dir / "docs"
    (base / "client1").mkdir(parents=True)
    (base / "client2").mkdir(parents=True)
    same = "Alice and Bob met in Paris."
    (base / "client1" / "shared.txt").write_text(same)
    (base / "client2" / "shared.txt").write_text(same)

    report = asyncio.run(svc.index_path(base, project="dupe-test"))
    assert report.indexed == 2, f"Expected 2 indexed, got {report.indexed} (errors={report.errors})"

    # Both paths must be retrievable from index_status, not just the
    # alphabetically-last winner.
    status = asyncio.run(svc.index_status(project="dupe-test"))
    file_paths = {entry.file_path for entry in status.files}
    assert any("client1" in p for p in file_paths), f"client1 missing from {file_paths}"
    assert any("client2" in p for p in file_paths), f"client2 missing from {file_paths}"
    assert status.total_docs == 2

    asyncio.run(svc.close())
