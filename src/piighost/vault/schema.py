"""Vault DDL and forward-only migrations."""

from __future__ import annotations

import sqlite3
import time

CURRENT_SCHEMA_VERSION = 2

_DDL = """
CREATE TABLE IF NOT EXISTS entities (
    token TEXT PRIMARY KEY,
    original TEXT NOT NULL,
    label TEXT NOT NULL,
    confidence REAL,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS doc_entities (
    doc_id TEXT NOT NULL,
    token TEXT NOT NULL REFERENCES entities(token),
    start_pos INTEGER,
    end_pos INTEGER,
    PRIMARY KEY (doc_id, token, start_pos)
);

CREATE TABLE IF NOT EXISTS indexed_files (
    doc_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    indexed_at INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schema_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_label ON entities(label);
CREATE INDEX IF NOT EXISTS idx_doc_entities_doc ON doc_entities(doc_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_indexed_files_path ON indexed_files(file_path);
"""

_MIGRATION_V1_TO_V2 = """
CREATE TABLE IF NOT EXISTS indexed_files (
    doc_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    indexed_at INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_indexed_files_path ON indexed_files(file_path);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotently create schema, run forward migrations, and stamp version."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_DDL)
    cur = conn.execute("SELECT COUNT(*) FROM schema_meta")
    if cur.fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO schema_meta (singleton, version, created_at) VALUES (1, ?, ?)",
            (CURRENT_SCHEMA_VERSION, int(time.time())),
        )
        conn.commit()
        return
    row = conn.execute("SELECT version FROM schema_meta WHERE singleton = 1").fetchone()
    if row and row[0] < 2:
        conn.executescript(_MIGRATION_V1_TO_V2)
        conn.execute("UPDATE schema_meta SET version = 2 WHERE singleton = 1")
        conn.commit()
