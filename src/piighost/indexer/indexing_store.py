"""Per-project metadata store for incremental indexing.

Separate SQLite file (``{project_dir}/indexing.sqlite``) so indexing
metadata does not pollute the PII vault schema.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

CURRENT_SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS indexed_files (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_mtime REAL NOT NULL,
    file_size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at REAL NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    entity_count INTEGER,
    chunk_count INTEGER,
    schema_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(project_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_indexed_files_project
    ON indexed_files(project_id);

CREATE INDEX IF NOT EXISTS idx_indexed_files_status
    ON indexed_files(project_id, status);

CREATE TABLE IF NOT EXISTS indexing_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
"""


class IndexingStore:
    """Per-project incremental-indexing metadata.

    One ``IndexingStore`` per SQLite file. Safe for single-connection use
    only; each ``_ProjectService`` owns one instance.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, db_path: Path) -> "IndexingStore":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_DDL)
        cur = conn.execute("SELECT COUNT(*) FROM indexing_meta")
        if cur.fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO indexing_meta (singleton, version, created_at)"
                " VALUES (1, ?, ?)",
                (CURRENT_SCHEMA_VERSION, int(time.time())),
            )
        return cls(conn)

    def close(self) -> None:
        self._conn.close()
