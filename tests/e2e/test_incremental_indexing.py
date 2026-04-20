"""E2E: incremental indexing — skip unchanged, reindex modified, remove doc."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault_dir = tmp_path / "vault"
    service = asyncio.run(PIIGhostService.create(vault_dir=vault_dir))
    yield service
    asyncio.run(service.close())


@pytest.fixture()
def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "contract.txt").write_text(
        "Alice is a legal consultant. The project is based in Paris."
    )
    (d / "report.txt").write_text(
        "The data processing agreement was submitted to the Paris DPA office."
    )
    (d / "memo.txt").write_text(
        "A meeting concluded with approval. Alice will follow up."
    )
    return d


def test_second_index_skips_all_unchanged(svc, docs):
    r1 = asyncio.run(svc.index_path(docs))
    assert r1.indexed == 3
    assert r1.unchanged == 0

    r2 = asyncio.run(svc.index_path(docs))
    assert r2.indexed == 0
    assert r2.unchanged == 3
    assert r2.errors == []


def test_force_flag_reindexes_all(svc, docs):
    asyncio.run(svc.index_path(docs))
    r2 = asyncio.run(svc.index_path(docs, force=True))
    assert r2.indexed == 3
    assert r2.unchanged == 0


def test_modified_file_is_reindexed(svc, tmp_path):
    d = tmp_path / "docs2"
    d.mkdir()
    f = d / "doc.txt"
    f.write_text("Alice works in Paris on GDPR contracts.")

    r1 = asyncio.run(svc.index_path(f))
    assert r1.indexed == 1

    # Modify mtime explicitly so the skip check detects a change
    new_mtime = f.stat().st_mtime + 2.0
    os.utime(f, (new_mtime, new_mtime))

    r2 = asyncio.run(svc.index_path(f))
    assert r2.indexed == 1
    assert r2.unchanged == 0


def test_remove_doc_removes_from_query_results(svc, tmp_path):
    d = tmp_path / "docs3"
    d.mkdir()
    f = d / "doc.txt"
    f.write_text("Alice works in Paris on legal contracts and compliance reviews.")

    asyncio.run(svc.index_path(f))
    result_before = asyncio.run(svc.query("legal compliance", k=5))
    assert len(result_before.hits) >= 1

    asyncio.run(svc.remove_doc(f))
    result_after = asyncio.run(svc.query("legal compliance", k=5))
    assert len(result_after.hits) == 0


def test_index_status_reflects_indexed_files(svc, docs):
    asyncio.run(svc.index_path(docs))
    status = asyncio.run(svc.index_status())
    assert status.total_docs == 3
    assert status.total_chunks >= 3
    indexed_paths = {f.file_path for f in status.files}
    for name in ("contract.txt", "report.txt", "memo.txt"):
        assert str(docs / name) in indexed_paths


def test_remove_doc_updates_index_status(svc, docs):
    asyncio.run(svc.index_path(docs))
    asyncio.run(svc.remove_doc(docs / "contract.txt"))
    status = asyncio.run(svc.index_status())
    assert status.total_docs == 2
    paths = {f.file_path for f in status.files}
    assert str(docs / "contract.txt") not in paths
