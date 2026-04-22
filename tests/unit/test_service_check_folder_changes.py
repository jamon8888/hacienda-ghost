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


def test_empty_folder_reports_empty_tier(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    r = asyncio.run(svc.check_folder_changes(str(folder)))
    assert r.tier == "empty"
    assert r.new == []
    assert r.modified == []
    assert r.deleted == []
    assert r.unchanged_count == 0


def test_two_new_files_report_small_tier(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "a.txt").write_text("hi")
    (folder / "b.txt").write_text("hello")
    r = asyncio.run(svc.check_folder_changes(str(folder)))
    assert r.tier == "small"
    assert {e.file_path for e in r.new} == {
        str((folder / "a.txt").resolve()),
        str((folder / "b.txt").resolve()),
    }


def test_after_index_folder_is_unchanged(svc, tmp_path):
    folder = tmp_path / "docs"; folder.mkdir()
    (folder / "a.txt").write_text("Alice in Paris")
    asyncio.run(svc.index_path(folder))
    r = asyncio.run(svc.check_folder_changes(str(folder)))
    assert r.tier == "empty"
    assert r.unchanged_count == 1
