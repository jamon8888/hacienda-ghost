"""Regression test: forget_subject must be serialized per project.

Two concurrent forget_subject(dry_run=False) calls on the same project
must not interleave their vault deletes / chunk rewrites — the second
caller waits for the first to finish.
"""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_concurrent_forget_subject_serializes(vault_dir, monkeypatch):
    """Two concurrent forget_subject calls do not interleave."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("forget-race"))
    proj = asyncio.run(svc._get_project("forget-race"))

    # Seed two distinct PII tokens
    proj._vault.upsert_entity(
        token="<<np:1>>", original="Alice", label="nom_personne", confidence=0.9,
    )
    proj._vault.upsert_entity(
        token="<<np:2>>", original="Bob", label="nom_personne", confidence=0.9,
    )

    async def both_forgets():
        # Two concurrent forgets, distinct token sets
        return await asyncio.gather(
            svc.forget_subject(
                tokens=["<<np:1>>"], project="forget-race", dry_run=False,
            ),
            svc.forget_subject(
                tokens=["<<np:2>>"], project="forget-race", dry_run=False,
            ),
        )

    r1, r2 = asyncio.run(both_forgets())
    # Both report success
    assert r1.dry_run is False
    assert r2.dry_run is False
    # Both tokens are gone from the vault (no partial state)
    assert proj._vault.get_by_token("<<np:1>>") is None
    assert proj._vault.get_by_token("<<np:2>>") is None

    asyncio.run(svc.close())


def test_concurrent_forget_holds_write_lock(vault_dir, monkeypatch):
    """While forget_subject is running, an index_path call waits for the lock."""
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("forget-lock"))
    proj = asyncio.run(svc._get_project("forget-lock"))
    proj._vault.upsert_entity(
        token="<<np:99>>", original="Charlie", label="nom_personne", confidence=0.9,
    )

    # Sanity: the same _write_lock object is reachable
    assert proj._write_lock is not None
    assert isinstance(proj._write_lock, asyncio.Lock)

    # Simulate "lock is held by forget" — manually acquire then forget should block
    async def assert_lock_blocks():
        await proj._write_lock.acquire()
        forget_task = asyncio.create_task(
            svc.forget_subject(
                tokens=["<<np:99>>"], project="forget-lock", dry_run=False,
            )
        )
        # Give the forget task a chance to start; it must NOT complete while we hold the lock
        await asyncio.sleep(0.1)
        assert not forget_task.done(), "forget_subject did not respect _write_lock"
        proj._write_lock.release()
        await forget_task

    asyncio.run(assert_lock_blocks())
    asyncio.run(svc.close())
