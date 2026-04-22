from __future__ import annotations

import asyncio

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    s = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield s
    asyncio.run(s.close())


def test_cancel_stops_loop_between_files(svc, tmp_path, monkeypatch):
    folder = tmp_path / "docs"; folder.mkdir()
    for i in range(5):
        (folder / f"f{i}.txt").write_text(f"file {i}")

    # Monkeypatch extract_text to cancel after second file starts processing
    from piighost.indexer import ingestor as ing
    real = ing.extract_text
    seen = {"n": 0}

    async def counting(path, **kw):
        seen["n"] += 1
        if seen["n"] == 2:
            # Trigger cancel after second file starts
            await svc.cancel_indexing(project="default")
        return await real(path, **kw)

    monkeypatch.setattr(ing, "extract_text", counting)
    r = asyncio.run(svc.index_path(folder, project="default"))
    # At least one file indexed, but not all 5 (cancel broke the loop)
    assert r.indexed + r.modified < 5


def test_cancel_nonexistent_project_is_noop(svc):
    r = asyncio.run(svc.cancel_indexing(project="no-such"))
    assert r.cancelled is True
    assert r.project == "no-such"
