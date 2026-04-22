from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    s = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield s
    asyncio.run(s.close())


def test_report_distinguishes_new_vs_modified(svc, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    a = folder / "a.txt"; a.write_text("Alice works in Paris")

    r1 = asyncio.run(svc.index_path(folder))
    assert r1.indexed == 1
    assert r1.modified == 0
    assert r1.unchanged == 0

    # Add a new file AND modify the existing one (bump mtime + content)
    a.write_text("Alice moved to Berlin")
    import os, time
    os.utime(a, (time.time(), time.time()))
    b = folder / "b.txt"; b.write_text("New doc")

    r2 = asyncio.run(svc.index_path(folder))
    assert r2.indexed == 1           # b.txt: new
    assert r2.modified == 1          # a.txt: content changed
    assert r2.unchanged == 0


def test_report_reports_deleted(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    a = folder / "a.txt"; a.write_text("hello")
    asyncio.run(svc.index_path(folder))
    a.unlink()
    r2 = asyncio.run(svc.index_path(folder))
    assert r2.deleted == 1
    assert r2.indexed == 0


def test_per_file_error_is_isolated(svc, tmp_path, monkeypatch):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "good.txt").write_text("Alice in Paris")
    bad = folder / "bad.txt"; bad.write_text("broken")

    # Monkeypatch extract_text to raise on bad.txt only
    from piighost.indexer import ingestor as ing
    real = ing.extract_text

    async def flaky(path, **kw):
        if path.name == "bad.txt":
            raise RuntimeError("simulated extraction failure")
        return await real(path, **kw)

    monkeypatch.setattr(ing, "extract_text", flaky)

    r = asyncio.run(svc.index_path(folder))
    assert r.indexed == 1
    assert len(r.errors) == 1
    assert "bad.txt" in r.errors[0]


def test_unchanged_still_skips_when_stat_matches(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "a.txt").write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder))
    r2 = asyncio.run(svc.index_path(folder))
    assert r2.unchanged == 1
    assert r2.indexed == 0
    assert r2.modified == 0
