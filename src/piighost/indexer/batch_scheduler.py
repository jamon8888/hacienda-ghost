# src/piighost/indexer/batch_scheduler.py
"""Classify a ChangeSet into a processing tier (empty / small / medium / large).

The tier determines how the service handles user consent:
  - EMPTY  : nothing to do
  - SMALL  : auto-index silently (≤2 files, <5 MB total)
  - MEDIUM : ask once per session (3-10 files or 5-50 MB)
  - LARGE  : always ask with time estimate (>10 files or >50 MB)
"""

from __future__ import annotations

import enum
from pathlib import Path

from piighost.indexer.change_detector import ChangeSet
from piighost.service.config import IncrementalSection


class BatchTier(str, enum.Enum):
    EMPTY = "empty"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


def _total_size(paths: list[Path]) -> int:
    """Sum on-disk sizes of *paths*, silently ignoring any OSError."""
    total = 0
    for p in paths:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def classify_batch(cs: ChangeSet, config: IncrementalSection) -> BatchTier:
    """Return the tier for *cs* given the threshold *config*.

    Only ``new`` and ``modified`` files count toward the threshold;
    ``deleted`` entries are tracked but do not require NER/embeddings work.
    """
    payload = cs.new + cs.modified
    n = len(payload)
    if n == 0 and not cs.deleted:
        return BatchTier.EMPTY
    total = _total_size(payload)

    if n <= config.small_max_files and total < config.small_max_bytes:
        return BatchTier.SMALL
    if n <= config.medium_max_files and total <= config.medium_max_bytes:
        return BatchTier.MEDIUM
    return BatchTier.LARGE
