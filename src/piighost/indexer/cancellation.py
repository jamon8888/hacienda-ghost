# src/piighost/indexer/cancellation.py
"""Per-project cancellation tokens for the incremental indexer.

The indexer checks ``token.is_cancelled`` between files (not mid-inference).
``CancellationRegistry`` is process-local and keyed by project name.
"""

from __future__ import annotations

import threading


class CancellationToken:
    """A simple one-way flag: once cancelled, cannot be un-cancelled.

    Create a fresh token via ``CancellationRegistry.reset()`` to start a
    new batch after cancellation.

    Uses ``threading.Event`` so that reads and writes of the flag are
    safe under free-threaded Python (3.13+ with the GIL disabled) and
    across ``concurrent.futures`` thread pools.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        """Set the cancellation flag. Idempotent."""
        self._event.set()


class CancellationRegistry:
    """Process-local store of per-project cancellation tokens.

    Thread-safe: all mutations are protected by a ``threading.Lock``.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, CancellationToken] = {}
        self._lock = threading.Lock()

    def get_or_create(self, project: str) -> CancellationToken:
        """Return the existing token for *project*, or create a fresh one."""
        with self._lock:
            tok = self._tokens.get(project)
            if tok is None:
                tok = CancellationToken()
                self._tokens[project] = tok
            return tok

    def reset(self, project: str) -> CancellationToken:
        """Replace the token for *project* with a fresh (uncancelled) one."""
        with self._lock:
            tok = CancellationToken()
            self._tokens[project] = tok
            return tok
