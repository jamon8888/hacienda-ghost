# tests/e2e/test_incremental_indexing_perf.py
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from piighost.service.core import PIIGhostService


pytestmark = pytest.mark.slow


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    s = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield s
    asyncio.run(s.close())


def _seed(folder: Path, n: int) -> None:
    folder.mkdir(exist_ok=True)
    for i in range(n):
        (folder / f"f{i}.txt").write_text(f"Alice works in Paris row {i}")


def test_detection_under_500ms_with_1000_unchanged_files(svc, tmp_path):
    folder = tmp_path / "f"
    _seed(folder, 1000)
    asyncio.run(svc.index_path(folder, project="p"))
    t0 = time.monotonic()
    r = asyncio.run(svc.check_folder_changes(str(folder), project="p"))
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert r.unchanged_count == 1000
    assert r.tier == "empty"
    assert elapsed_ms < 500, f"detection took {elapsed_ms:.0f}ms"


def test_incremental_is_faster_than_full_reindex(svc, tmp_path):
    folder = tmp_path / "f"
    _seed(folder, 1000)
    t_full = time.monotonic()
    asyncio.run(svc.index_path(folder, project="p"))
    t_full = time.monotonic() - t_full

    # Add 10 new files, then re-index incrementally
    for i in range(1000, 1010):
        (folder / f"f{i}.txt").write_text(f"Bob row {i}")

    t_inc = time.monotonic()
    r = asyncio.run(svc.index_path(folder, project="p"))
    t_inc = time.monotonic() - t_inc

    assert r.indexed == 10
    assert r.unchanged == 1000
    # Incremental (10 files) should be well under 1/3 of full (1000 files)
    assert t_inc < t_full / 3, f"incremental {t_inc:.2f}s not << full {t_full:.2f}s"
