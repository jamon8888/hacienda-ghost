import asyncio
import pytest
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc_with_docs(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault_dir = tmp_path / "vault"
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works in Paris")
    (docs / "b.txt").write_text("Legal contracts are reviewed weekly")
    asyncio.run(svc.index_path(docs))
    return svc, docs


def test_index_status_total_docs(svc_with_docs):
    svc, _ = svc_with_docs
    status = asyncio.run(svc.index_status())
    assert status.total_docs == 2
    asyncio.run(svc.close())


def test_index_status_total_chunks(svc_with_docs):
    svc, _ = svc_with_docs
    status = asyncio.run(svc.index_status())
    assert status.total_chunks >= 2
    asyncio.run(svc.close())


def test_index_status_files_list(svc_with_docs):
    svc, docs = svc_with_docs
    status = asyncio.run(svc.index_status())
    paths = {f.file_path for f in status.files}
    assert str(docs / "a.txt") in paths
    assert str(docs / "b.txt") in paths
    asyncio.run(svc.close())


def test_index_status_empty_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    svc = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    status = asyncio.run(svc.index_status())
    assert status.total_docs == 0
    assert status.total_chunks == 0
    assert status.files == []
    asyncio.run(svc.close())
