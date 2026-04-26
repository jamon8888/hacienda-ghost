"""Tests for the 4 RPCs added for the hacienda Cowork plugin:
resolve_project_for_folder, bootstrap_client_folder, folder_status,
session_audit_read, session_audit_append."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir))


def test_resolve_project_for_folder_returns_folder_and_project(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client-acme"
    folder.mkdir()
    result = asyncio.run(svc.resolve_project_for_folder(folder))
    assert result["folder"] == str(folder.resolve())
    # The exact project depends on derive_project_from_path's parent walk,
    # but it must be a non-empty string.
    assert isinstance(result["project"], str) and result["project"]
    asyncio.run(svc.close())


def test_bootstrap_client_folder_creates_project(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client-bravo"
    folder.mkdir()

    result = asyncio.run(svc.bootstrap_client_folder(folder))
    assert result["folder"] == str(folder.resolve())
    project_name = result["project"]

    # The project must now appear in the registry
    projects = asyncio.run(svc.list_projects())
    names = {p.name for p in projects}
    assert project_name in names

    # Re-running is idempotent (no error, created=False the second time)
    result2 = asyncio.run(svc.bootstrap_client_folder(folder))
    assert result2["project"] == project_name
    assert result2["created"] is False
    asyncio.run(svc.close())


def test_folder_status_empty_then_indexed(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "docs-foxtrot"
    folder.mkdir()

    # Empty before any indexing
    status = asyncio.run(svc.folder_status(folder))
    assert status["state"] == "empty"
    assert status["total_docs"] == 0

    # Index a file, status flips to "indexed"
    (folder / "note.txt").write_text("Carol works at ACME.")
    asyncio.run(svc.bootstrap_client_folder(folder))
    project_name = (asyncio.run(svc.resolve_project_for_folder(folder)))["project"]
    asyncio.run(svc.index_path(folder, project=project_name))

    status2 = asyncio.run(svc.folder_status(folder))
    assert status2["state"] == "indexed"
    assert status2["total_docs"] >= 1
    assert status2["last_indexed_at"] is not None
    asyncio.run(svc.close())


def test_session_audit_append_then_read_round_trip(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("test-audit"))

    # Append two events
    asyncio.run(svc.session_audit_append(
        "test-audit", op="custom_op", token=None, caller_kind="skill"
    ))
    asyncio.run(svc.session_audit_append(
        "test-audit", op="another_op", token="tok123",
        caller_kind="skill", metadata={"reason": "test"}
    ))

    result = asyncio.run(svc.session_audit_read("test-audit"))
    assert result["session_id"] == "test-audit"
    ops = [e["op"] for e in result["events"]]
    assert "custom_op" in ops
    assert "another_op" in ops
    asyncio.run(svc.close())


def test_session_audit_read_unknown_project_returns_empty(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    result = asyncio.run(svc.session_audit_read("does-not-exist"))
    assert result == {"session_id": "does-not-exist", "events": []}
    asyncio.run(svc.close())
