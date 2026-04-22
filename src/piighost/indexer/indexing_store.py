"""Per-project metadata store for incremental indexing.

Separate SQLite file (``{project_dir}/indexing.sqlite``) so indexing
metadata does not pollute the PII vault schema.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class FileRecord:
    """Metadata for a single indexed file."""

    project_id: str
    file_path: str
    file_mtime: float
    file_size: int
    content_hash: str
    indexed_at: float
    status: str  # 'success' | 'error' | 'deleted'
    error_message: str | None
    entity_count: int | None
    chunk_count: int | None


def _row_to_record(row: sqlite3.Row) -> FileRecord:
    """Convert a database row to a FileRecord."""
    return FileRecord(
        project_id=row["project_id"],
        file_path=row["file_path"],
        file_mtime=row["file_mtime"],
        file_size=row["file_size"],
        content_hash=row["content_hash"],
        indexed_at=row["indexed_at"],
        status=row["status"],
        error_message=row["error_message"],
        entity_count=row["entity_count"],
        chunk_count=row["chunk_count"],
    )


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

    def upsert(self, rec: FileRecord) -> None:
        """Insert or replace a file record by project_id and file_path."""
        self._conn.execute(
            """
            INSERT INTO indexed_files (
                project_id, file_path, file_mtime, file_size, content_hash,
                indexed_at, status, error_message, entity_count, chunk_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, file_path) DO UPDATE SET
                file_mtime=excluded.file_mtime,
                file_size=excluded.file_size,
                content_hash=excluded.content_hash,
                indexed_at=excluded.indexed_at,
                status=excluded.status,
                error_message=excluded.error_message,
                entity_count=excluded.entity_count,
                chunk_count=excluded.chunk_count
            """,
            (
                rec.project_id,
                rec.file_path,
                rec.file_mtime,
                rec.file_size,
                rec.content_hash,
                rec.indexed_at,
                rec.status,
                rec.error_message,
                rec.entity_count,
                rec.chunk_count,
            ),
        )

    def get_by_path(self, project_id: str, file_path: str) -> FileRecord | None:
        """Retrieve a file record by project_id and file_path."""
        row = self._conn.execute(
            "SELECT * FROM indexed_files WHERE project_id = ? AND file_path = ?",
            (project_id, file_path),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def list_for_project(self, project_id: str) -> list[FileRecord]:
        """List all file records for a project."""
        rows = self._conn.execute(
            "SELECT * FROM indexed_files WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def delete_by_path(self, project_id: str, file_path: str) -> bool:
        """Delete a file record by project_id and file_path.

        Returns True if a record was deleted, False if no record existed.
        """
        cursor = self._conn.execute(
            "DELETE FROM indexed_files WHERE project_id = ? AND file_path = ?",
            (project_id, file_path),
        )
        return cursor.rowcount > 0

    def mark_deleted(self, project_id: str, file_path: str) -> None:
        """Mark a file record as deleted by setting status to 'deleted'."""
        self._conn.execute(
            "UPDATE indexed_files SET status = 'deleted' WHERE project_id = ? AND file_path = ?",
            (project_id, file_path),
        )
