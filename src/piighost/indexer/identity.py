from __future__ import annotations

import hashlib
from pathlib import Path


def content_hash_full(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def content_hash(path: Path) -> str:
    """Return the first 16 hex characters of the SHA-256 of *path*.

    Intended as a fast change-detection fingerprint, not a collision-resistant
    unique identifier. Use ``content_hash_full`` where uniqueness is required.
    """
    return content_hash_full(path)[:16]


def file_fingerprint(path: Path) -> tuple[float, int]:
    """Return *(mtime, size)* for *path* using ``path.stat()``.

    Returns ``(st_mtime: float, st_size: int)``.
    """
    stat = path.stat()
    return (stat.st_mtime, stat.st_size)
