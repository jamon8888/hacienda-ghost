# tests/unit/indexer/test_batch_scheduler.py
from pathlib import Path

import pytest

from piighost.indexer.batch_scheduler import BatchTier, classify_batch
from piighost.indexer.change_detector import ChangeSet
from piighost.service.config import IncrementalSection


def _files(tmp_path, sizes):
    out = []
    for i, size in enumerate(sizes):
        f = tmp_path / f"f{i}.txt"
        f.write_bytes(b"x" * size)
        out.append(f)
    return out


def test_no_changes_is_empty(tmp_path):
    cs = ChangeSet()
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.EMPTY


def test_two_small_files_is_small(tmp_path):
    files = _files(tmp_path, [1024, 2048])
    cs = ChangeSet(new=files)
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.SMALL


def test_five_files_is_medium(tmp_path):
    files = _files(tmp_path, [100] * 5)
    cs = ChangeSet(new=files)
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.MEDIUM


def test_twenty_files_is_large(tmp_path):
    files = _files(tmp_path, [10] * 20)
    cs = ChangeSet(new=files)
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.LARGE


def test_large_total_size_triggers_large(tmp_path):
    # 2 files but total 60 MB → large
    big = tmp_path / "big.bin"
    big.write_bytes(b"\0" * (60 * 1024 * 1024))
    small = tmp_path / "s.txt"
    small.write_bytes(b"x")
    cs = ChangeSet(new=[big, small])
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.LARGE


def test_modified_counted_same_as_new(tmp_path):
    files = _files(tmp_path, [100] * 5)
    cs = ChangeSet(modified=files)
    tier = classify_batch(cs, IncrementalSection())
    assert tier is BatchTier.MEDIUM
