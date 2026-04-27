"""Per-project metadata store for incremental indexing.

Separate SQLite file (``{project_dir}/indexing.sqlite``) so indexing
metadata does not pollute the PII vault schema.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

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

CREATE TABLE IF NOT EXISTS documents_meta (
    project_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'autre',
    doc_type_confidence REAL NOT NULL DEFAULT 0.0,
    doc_date INTEGER,
    doc_date_source TEXT NOT NULL DEFAULT 'none',
    doc_title TEXT,
    doc_subject TEXT,
    doc_authors_json TEXT NOT NULL DEFAULT '[]',
    doc_language TEXT,
    doc_page_count INTEGER,
    doc_format TEXT NOT NULL DEFAULT '',
    is_encrypted_source INTEGER NOT NULL DEFAULT 0,
    parties_json TEXT NOT NULL DEFAULT '[]',
    dossier_id TEXT NOT NULL DEFAULT '',
    extracted_at REAL NOT NULL,
    PRIMARY KEY (project_id, doc_id)
);

CREATE INDEX IF NOT EXISTS idx_docmeta_dossier
    ON documents_meta(project_id, dossier_id);
CREATE INDEX IF NOT EXISTS idx_docmeta_doctype
    ON documents_meta(project_id, doc_type);
CREATE INDEX IF NOT EXISTS idx_docmeta_date
    ON documents_meta(project_id, doc_date);
CREATE INDEX IF NOT EXISTS idx_docmeta_language
    ON documents_meta(project_id, doc_language);
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


def _row_to_doc_meta(row: sqlite3.Row) -> "DocumentMetadata":
    """Convert a documents_meta row to a DocumentMetadata."""
    import json as _json
    from piighost.service.models import DocumentMetadata
    return DocumentMetadata(
        doc_id=row["doc_id"],
        doc_type=row["doc_type"],
        doc_type_confidence=row["doc_type_confidence"],
        doc_date=row["doc_date"],
        doc_date_source=row["doc_date_source"],
        doc_title=row["doc_title"],
        doc_subject=row["doc_subject"],
        doc_authors=_json.loads(row["doc_authors_json"] or "[]"),
        doc_language=row["doc_language"],
        doc_page_count=row["doc_page_count"],
        doc_format=row["doc_format"],
        is_encrypted_source=bool(row["is_encrypted_source"]),
        parties=_json.loads(row["parties_json"] or "[]"),
        dossier_id=row["dossier_id"],
        extracted_at=row["extracted_at"],
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
        # Give concurrent readers / a second writer up to 5 s before raising
        # OperationalError.  The indexer's batch() holds BEGIN IMMEDIATE while
        # async I/O (extraction + embedding) runs, so a small timeout avoids
        # an immediate crash if two index_path calls race on the same project.
        conn.execute("PRAGMA busy_timeout=5000")
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

    def list_errors(
        self,
        project_id: str,
        *,
        limit: int = 50,
    ) -> list[FileRecord]:
        """Return up to ``limit`` most-recent ``status='error'`` rows for
        ``project_id``, ordered by ``indexed_at`` DESC.

        The ``(project_id, status)`` index covers the predicate; the
        ``ORDER BY indexed_at DESC LIMIT N`` clause is satisfied by a
        small in-memory sort, which is fine at the limits we care about
        (default 50, never more than a few hundred in practice)."""
        cur = self._conn.execute(
            "SELECT * FROM indexed_files "
            "WHERE project_id = ? AND status = 'error' "
            "ORDER BY indexed_at DESC "
            "LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_record(row) for row in cur.fetchall()]

    def count_errors(self, project_id: str) -> int:
        """Return the total number of ``status='error'`` rows for
        ``project_id``, ignoring any limit. Used as the truncation
        indicator for :meth:`list_errors`."""
        cur = self._conn.execute(
            "SELECT COUNT(*) AS n FROM indexed_files "
            "WHERE project_id = ? AND status = 'error'",
            (project_id,),
        )
        row = cur.fetchone()
        return int(row["n"]) if row else 0

    # ---- documents_meta CRUD ----

    def upsert_document_meta(
        self, project_id: str, meta: "DocumentMetadata",
    ) -> None:
        import json as _json
        self._conn.execute(
            """
            INSERT INTO documents_meta (
                project_id, doc_id, doc_type, doc_type_confidence,
                doc_date, doc_date_source, doc_title, doc_subject,
                doc_authors_json, doc_language, doc_page_count, doc_format,
                is_encrypted_source, parties_json, dossier_id, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, doc_id) DO UPDATE SET
                doc_type = excluded.doc_type,
                doc_type_confidence = excluded.doc_type_confidence,
                doc_date = excluded.doc_date,
                doc_date_source = excluded.doc_date_source,
                doc_title = excluded.doc_title,
                doc_subject = excluded.doc_subject,
                doc_authors_json = excluded.doc_authors_json,
                doc_language = excluded.doc_language,
                doc_page_count = excluded.doc_page_count,
                doc_format = excluded.doc_format,
                is_encrypted_source = excluded.is_encrypted_source,
                parties_json = excluded.parties_json,
                dossier_id = excluded.dossier_id,
                extracted_at = excluded.extracted_at
            """,
            (
                project_id, meta.doc_id, meta.doc_type, meta.doc_type_confidence,
                meta.doc_date, meta.doc_date_source, meta.doc_title, meta.doc_subject,
                _json.dumps(meta.doc_authors), meta.doc_language, meta.doc_page_count,
                meta.doc_format, int(meta.is_encrypted_source),
                _json.dumps(meta.parties), meta.dossier_id, meta.extracted_at,
            ),
        )

    def get_document_meta(
        self, project_id: str, doc_id: str,
    ) -> "DocumentMetadata | None":
        cur = self._conn.execute(
            "SELECT * FROM documents_meta WHERE project_id = ? AND doc_id = ?",
            (project_id, doc_id),
        )
        row = cur.fetchone()
        return _row_to_doc_meta(row) if row else None

    def documents_meta_for(
        self, project_id: str, doc_ids: list[str],
    ) -> list["DocumentMetadata"]:
        if not doc_ids:
            return []
        placeholders = ",".join("?" * len(doc_ids))
        cur = self._conn.execute(
            f"SELECT * FROM documents_meta "
            f"WHERE project_id = ? AND doc_id IN ({placeholders})",
            (project_id, *doc_ids),
        )
        return [_row_to_doc_meta(r) for r in cur.fetchall()]

    def list_documents_meta(
        self, project_id: str, *,
        dossier_id: str | None = None, doc_type: str | None = None,
        limit: int = 1000, offset: int = 0,
    ) -> list["DocumentMetadata"]:
        clauses = ["project_id = ?"]
        params: list = [project_id]
        if dossier_id is not None:
            clauses.append("dossier_id = ?")
            params.append(dossier_id)
        if doc_type is not None:
            clauses.append("doc_type = ?")
            params.append(doc_type)
        params.extend([limit, offset])
        cur = self._conn.execute(
            f"SELECT * FROM documents_meta WHERE {' AND '.join(clauses)} "
            f"ORDER BY extracted_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [_row_to_doc_meta(r) for r in cur.fetchall()]

    def delete_document_meta(self, project_id: str, doc_id: str) -> None:
        self._conn.execute(
            "DELETE FROM documents_meta WHERE project_id = ? AND doc_id = ?",
            (project_id, doc_id),
        )

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Context manager for atomic batch operations.

        Wraps operations in BEGIN IMMEDIATE / COMMIT / ROLLBACK.
        The store uses autocommit (isolation_level=None), so transactions
        must be opened and closed explicitly.
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")


def backfill_from_vault(
    store: IndexingStore,
    vault: object,
    project_id: str,
) -> int:
    """One-shot migration: copy ``vault.indexed_files`` rows into ``store``.

    Safe to call repeatedly — records a ``backfill_done`` flag in an
    auxiliary ``indexing_kv`` table.  Returns the number of rows copied on
    this call (0 on subsequent calls).
    """
    if _has_kv(store):
        row = store._conn.execute(
            "SELECT value FROM indexing_kv WHERE key = 'backfill_done'"
        ).fetchone()
        if row is not None:
            return 0

    _ensure_kv_table(store)
    inserted = 0
    with store.batch():
        for r in vault.list_indexed_files(limit=100_000, offset=0):
            path = Path(r.file_path)
            if path.exists():
                size = path.stat().st_size
                status = "success"
            else:
                size = 0
                status = "deleted"
            # Legacy vault rows stored 16-char content_hash; new rows use 64-char.
            # We keep the legacy value as-is: _hash_matches() in ChangeDetector
            # handles the prefix comparison so these rows still trigger
            # unchanged detection correctly.
            store.upsert(FileRecord(
                project_id=project_id,
                file_path=str(path),
                file_mtime=float(r.mtime),
                file_size=size,
                content_hash=r.content_hash,
                indexed_at=float(r.indexed_at),
                status=status,
                error_message=None,
                entity_count=None,
                chunk_count=r.chunk_count,
            ))
            inserted += 1
        store._conn.execute(
            "INSERT OR REPLACE INTO indexing_kv (key, value)"
            " VALUES ('backfill_done', '1')"
        )
    return inserted


def _ensure_kv_table(store: IndexingStore) -> None:
    """Create the ``indexing_kv`` auxiliary table if it does not exist."""
    store._conn.execute(
        "CREATE TABLE IF NOT EXISTS indexing_kv ("
        "  key TEXT PRIMARY KEY,"
        "  value TEXT NOT NULL"
        ")"
    )


def _has_kv(store: IndexingStore) -> bool:
    """Return True iff the ``indexing_kv`` table exists in *store*."""
    row = store._conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type='table' AND name='indexing_kv'"
    ).fetchone()
    return row is not None
