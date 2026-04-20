"""E2E: Sprint 1-4 state migrates to Sprint 5 layout transparently."""

from __future__ import annotations

import asyncio
import shutil

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def legacy_vault(tmp_path, monkeypatch):
    """Create a vault, populate it, then move files back to the v2 layout to simulate legacy state."""
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault = tmp_path / "vault"

    svc = asyncio.run(PIIGhostService.create(vault_dir=vault))
    asyncio.run(svc.anonymize("Alice was here"))
    asyncio.run(svc.close())

    # Move projects/default/* back to top level to simulate v2 layout.
    # On Windows, subdirectories (e.g. .piighost/lance) prevent rmdir, so we
    # move each child recursively then use shutil.rmtree for the now-possibly-
    # non-empty projects tree (handles nested dirs on all platforms).
    default = vault / "projects" / "default"
    for child in default.iterdir():
        dst = vault / child.name
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        shutil.move(str(child), str(dst))
    shutil.rmtree(vault / "projects")
    (vault / "projects.db").unlink()

    yield vault


def test_v2_vault_loads_as_v3_default_project(legacy_vault, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")

    svc = asyncio.run(PIIGhostService.create(vault_dir=legacy_vault))
    try:
        assert (legacy_vault / "projects" / "default" / "vault.db").exists()
        assert not (legacy_vault / "vault.db").exists()

        projects = asyncio.run(svc.list_projects())
        names = {p.name for p in projects}
        assert "default" in names

        stats = asyncio.run(svc.vault_stats(project="default"))
        assert stats.total >= 1
    finally:
        asyncio.run(svc.close())


def test_v2_tokens_still_rehydrate_after_migration(legacy_vault, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")

    svc = asyncio.run(PIIGhostService.create(vault_dir=legacy_vault))
    try:
        r = asyncio.run(svc.anonymize("Alice was here", project="default"))
        rehydrated = asyncio.run(svc.rehydrate(r.anonymized, project="default"))
        assert rehydrated.unknown_tokens == []
        assert "Alice" in rehydrated.text
    finally:
        asyncio.run(svc.close())
