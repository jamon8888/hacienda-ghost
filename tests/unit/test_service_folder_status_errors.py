"""Tests for the new errors[] / errors_truncated / total_errors fields
on PIIGhostService.folder_status. The 'state' / 'total_docs' /
'last_indexed_at' fields are covered by test_service_hacienda_rpcs.py."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.indexer.indexing_store import FileRecord
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir))


def _seed_error_row(svc, project: str, *, path: str, when: float, msg: str) -> None:
    """Reach into the project's IndexingStore and write one error row.
    Bypasses index_path so the test does not depend on extractor stack."""
    proj = asyncio.run(svc._get_project(project, auto_create=True))
    proj._indexing_store.upsert(FileRecord(
        project_id=project,
        file_path=path,
        file_mtime=0.0,
        file_size=0,
        content_hash="",
        indexed_at=when,
        status="error",
        error_message=msg,
        entity_count=None,
        chunk_count=None,
    ))


def test_folder_status_empty_project_returns_no_errors(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client-empty"
    folder.mkdir()

    status = asyncio.run(svc.folder_status(folder))
    assert status["errors"] == []
    assert status["errors_truncated"] is False
    assert status["total_errors"] == 0
    asyncio.run(svc.close())


def test_folder_status_returns_categorised_errors(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client-three"
    folder.mkdir()

    # Bootstrap so the project exists, then seed 3 error rows directly.
    boot = asyncio.run(svc.bootstrap_client_folder(folder))
    project = boot["project"]
    _seed_error_row(svc, project, path=str(folder / "a.pdf"),
                    when=300.0, msg="ExtractionError: file is password-protected")
    _seed_error_row(svc, project, path=str(folder / "b.pdf"),
                    when=200.0, msg="ExtractionError: file is corrupt")
    _seed_error_row(svc, project, path=str(folder / "c.heic"),
                    when=100.0, msg="ExtractionError: unsupported file type")

    status = asyncio.run(svc.folder_status(folder))
    assert status["total_errors"] == 3
    assert status["errors_truncated"] is False
    assert len(status["errors"]) == 3

    # Newest first
    cats = [e["category"] for e in status["errors"]]
    assert cats == ["password_protected", "corrupt", "unsupported_format"]

    # Sanitisation: file_name is basename only
    names = [e["file_name"] for e in status["errors"]]
    assert names == ["a.pdf", "b.pdf", "c.heic"]
    # No raw error message appears in any field
    for e in status["errors"]:
        assert "password-protected" not in e["category"]
        assert "ExtractionError" not in e["category"]

    paths = [e["file_path"] for e in status["errors"]]
    assert paths == [str(folder / "a.pdf"), str(folder / "b.pdf"), str(folder / "c.heic")]

    assert [e["indexed_at"] for e in status["errors"]] == [300, 200, 100]

    VALID_CATEGORIES = {"password_protected", "corrupt", "unsupported_format", "timeout", "other"}
    for e in status["errors"]:
        assert e["category"] in VALID_CATEGORIES

    asyncio.run(svc.close())


def test_folder_status_truncates_at_50(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client-many"
    folder.mkdir()

    boot = asyncio.run(svc.bootstrap_client_folder(folder))
    project = boot["project"]
    for i in range(60):
        _seed_error_row(svc, project, path=str(folder / f"f{i}.pdf"),
                        when=float(i),
                        msg="ExtractionError: file is corrupt")

    status = asyncio.run(svc.folder_status(folder))
    assert status["total_errors"] == 60
    assert status["errors_truncated"] is True
    assert len(status["errors"]) == 50
    # Newest first → f59 is at index 0
    assert status["errors"][0]["file_name"] == "f59.pdf"
    asyncio.run(svc.close())
