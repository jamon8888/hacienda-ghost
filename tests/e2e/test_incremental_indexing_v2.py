# tests/e2e/test_incremental_indexing_v2.py
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


def test_add_files_in_two_waves(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    for i in range(5):
        (folder / f"a{i}.txt").write_text(f"Alice in Paris {i}")
    r1 = asyncio.run(svc.index_path(folder, project="proj"))
    assert r1.indexed == 5

    for i in range(3):
        (folder / f"b{i}.txt").write_text(f"Bob in Berlin {i}")
    r2 = asyncio.run(svc.index_path(folder, project="proj"))
    assert r2.indexed == 3
    assert r2.unchanged == 5


def test_modify_file_triggers_reindex(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    f = folder / "c.txt"; f.write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder, project="proj"))

    # Change content AND bump mtime to ensure detector picks it up
    import os, time
    f.write_text("Alice in Berlin, completely different content now.")
    os.utime(f, (time.time() + 10, time.time() + 10))
    r = asyncio.run(svc.index_path(folder, project="proj"))
    assert r.modified == 1


def test_delete_is_reported(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    f = folder / "d.txt"; f.write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder, project="proj"))
    f.unlink()
    r = asyncio.run(svc.index_path(folder, project="proj"))
    assert r.deleted == 1


def test_check_folder_changes_sees_deletion(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    f = folder / "d.txt"; f.write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder, project="proj"))
    f.unlink()
    changes = asyncio.run(svc.check_folder_changes(str(folder), project="proj"))
    assert changes.deleted == [str(f.resolve())]


def test_multi_project_isolation(svc, tmp_path):
    a = tmp_path / "A"; a.mkdir()
    b = tmp_path / "B"; b.mkdir()
    (a / "x.txt").write_text("Alice in Paris")
    asyncio.run(svc.index_path(a, project="A"))

    # Project B has no entries — check_folder_changes on B sees only new
    (b / "y.txt").write_text("Bob in Berlin")
    r_b = asyncio.run(svc.check_folder_changes(str(b), project="B"))
    assert len(r_b.new) == 1
    # A is still fully indexed
    r_a = asyncio.run(svc.check_folder_changes(str(a), project="A"))
    assert r_a.unchanged_count == 1


def test_corrupted_file_does_not_break_batch(svc, tmp_path, monkeypatch):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "good.txt").write_text("Alice in Paris")
    (folder / "bad.pdf").write_bytes(b"NOT-A-PDF")
    r = asyncio.run(svc.index_path(folder, project="proj"))
    # good file succeeds even if bad one fails/skips
    assert r.indexed >= 1


def test_force_true_preserves_old_behavior(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "a.txt").write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder, project="proj"))
    r = asyncio.run(svc.index_path(folder, project="proj", force=True))
    assert r.indexed == 1
    assert r.unchanged == 0
    assert r.modified == 0
