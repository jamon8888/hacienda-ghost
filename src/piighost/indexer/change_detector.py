# src/piighost/indexer/change_detector.py
"""Detect new / modified / unchanged / deleted files for a project.

Pure and side-effect-free: reads the filesystem + IndexingStore, returns
a :class:`ChangeSet`. The indexer is responsible for acting on it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from piighost.indexer.identity import content_hash_full, file_fingerprint
from piighost.indexer.indexing_store import IndexingStore
from piighost.indexer.ingestor import list_document_paths

# 2-second epsilon covers FAT32's coarse mtime resolution (2s granularity).
# On ext4/NTFS/APFS the extra slack is harmless: when mtime matches but
# size also matches, we skip the hash; if sizes differ we still hash.
_STAT_EPSILON = 2.0


def _hash_matches(stored: str, fresh_full: str) -> bool:
    """Compare stored hash to fresh full 64-char SHA-256.

    Legacy vault rows stored a 16-char prefix; new rows store the full
    64-char hex.  This helper handles both cases transparently.
    """
    if len(stored) == 16:
        return fresh_full.startswith(stored)
    return fresh_full == stored


@dataclass
class ChangeSet:
    new: list[Path] = field(default_factory=list)
    modified: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Defensive copies so callers cannot mutate the change set.
        self.new = list(self.new)
        self.modified = list(self.modified)
        self.unchanged = list(self.unchanged)
        self.deleted = list(self.deleted)

    def total_changes(self) -> int:
        return len(self.new) + len(self.modified) + len(self.deleted)


class ChangeDetector:
    def __init__(self, *, store: IndexingStore, project_id: str) -> None:
        self._store = store
        self._project_id = project_id

    async def scan_async(self, folder: Path, *, recursive: bool = True) -> ChangeSet:
        paths = await list_document_paths(folder, recursive=recursive)
        return self._classify(paths)

    def scan(self, folder: Path, *, recursive: bool = True) -> ChangeSet:
        """Synchronous wrapper for use from synchronous code with no running event loop.

        Use ``scan_async()`` when calling from an async context.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass  # No running loop — safe to call asyncio.run()
        else:
            raise RuntimeError(
                "ChangeDetector.scan() cannot be called from a running event loop. "
                "Use scan_async() instead."
            )
        return asyncio.run(self.scan_async(folder, recursive=recursive))

    def _classify(self, paths: list[Path]) -> ChangeSet:
        on_disk = {p.resolve() for p in paths}
        # Only consider successfully-indexed files for skip detection.
        # Files with status "deleted" or "error" are excluded:
        #   - "deleted"  → we know they are gone, no path on disk
        #   - "error"    → stored content_hash is "" (poisoned); mtime+size
        #                  may still match if the file is unchanged, which
        #                  would permanently classify it as "unchanged" instead
        #                  of retrying it.  Filtering it out makes it appear
        #                  as "new" so every run retries the failed file.
        indexed = {
            r.file_path: r
            for r in self._store.list_for_project(self._project_id)
            if r.status == "success"
        }

        new: list[Path] = []
        modified: list[Path] = []
        unchanged: list[Path] = []

        for p in sorted(on_disk):
            key = str(p)
            rec = indexed.pop(key, None)
            if rec is None:
                new.append(p)
                continue
            mtime, size = file_fingerprint(p)
            if abs(mtime - rec.file_mtime) < _STAT_EPSILON and size == rec.file_size:
                unchanged.append(p)
                continue
            # Fall back to content hash
            if _hash_matches(rec.content_hash, content_hash_full(p)):
                unchanged.append(p)
            else:
                modified.append(p)

        # Whatever remains in ``indexed`` after popping disk matches is deleted
        deleted = [Path(k).resolve() for k in sorted(indexed.keys())]
        return ChangeSet(new=new, modified=modified, unchanged=unchanged, deleted=deleted)
