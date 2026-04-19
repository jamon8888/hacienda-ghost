import sqlite3
from pathlib import Path

from piighost.vault.schema import CURRENT_SCHEMA_VERSION, ensure_schema


def test_creates_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"entities", "doc_entities", "schema_meta"}.issubset(tables)
    assert "audit_log" not in tables
    conn.close()


def test_stamps_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    version = conn.execute("SELECT version FROM schema_meta").fetchone()[0]
    assert version == CURRENT_SCHEMA_VERSION
    conn.close()


def test_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    ensure_schema(conn)  # second call must not raise
    (count,) = conn.execute("SELECT COUNT(*) FROM schema_meta").fetchone()
    assert count == 1
    conn.close()


def test_wal_mode_enabled(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    assert mode.lower() == "wal"
    conn.close()
