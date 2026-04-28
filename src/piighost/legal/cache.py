"""LegalCache — SQLite TTL cache for OpenLégi responses.

Keyed on ``sha256(tool || canonical_json(args))``. TTL strategy is
caller-decided (Task 7's service methods pick 7 days for verify, 5
minutes for freeform search). Cache survives daemon restarts.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS legal_cache (
    cache_key   TEXT PRIMARY KEY,
    tool        TEXT NOT NULL,
    response    TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    hits        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_legal_cache_created ON legal_cache(created_at);
"""


class LegalCache:
    """SQLite-backed cache for OpenLégi tool responses."""

    def __init__(self, vault_dir: Path) -> None:
        self._path = Path(vault_dir) / "legal_cache.sqlite"
        self._conn = sqlite3.connect(str(self._path))
        self._conn.executescript(_SCHEMA)

    @staticmethod
    def _key(tool: str, args: dict) -> str:
        """sha256(tool || canonical_json(args)). Deterministic across
        equal-but-differently-ordered dicts."""
        payload = tool + "::" + json.dumps(
            args, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, tool: str, args: dict) -> Any:
        """Return cached response (parsed dict) or None on miss/expired."""
        key = self._key(tool, args)
        row = self._conn.execute(
            "SELECT response, created_at, ttl_seconds FROM legal_cache "
            "WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        response_json, created_at, ttl = row
        if time.time() > created_at + ttl:
            return None
        # Hit — bump counter
        self._conn.execute(
            "UPDATE legal_cache SET hits = hits + 1 WHERE cache_key = ?",
            (key,),
        )
        self._conn.commit()
        return json.loads(response_json)

    def set(self, tool: str, args: dict, *, response: Any, ttl_seconds: int) -> None:
        key = self._key(tool, args)
        self._conn.execute(
            "INSERT OR REPLACE INTO legal_cache "
            "(cache_key, tool, response, created_at, ttl_seconds, hits) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (key, tool, json.dumps(response), int(time.time()), ttl_seconds),
        )
        self._conn.commit()

    def clear(self) -> int:
        """Remove all entries. Returns the count of removed rows."""
        n = self._conn.execute("SELECT COUNT(*) FROM legal_cache").fetchone()[0]
        self._conn.execute("DELETE FROM legal_cache")
        self._conn.commit()
        return n

    def stats(self) -> dict:
        rows = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(hits), 0) FROM legal_cache"
        ).fetchone()
        return {"entries": rows[0], "total_hits": rows[1]}

    def close(self) -> None:
        self._conn.close()
