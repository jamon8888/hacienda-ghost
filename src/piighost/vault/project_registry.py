"""Per-vault registry of logical projects."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


_VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


class InvalidProjectName(ValueError):
    """Raised when a project name violates the allowed character set or length."""


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    description: str
    created_at: int
    last_accessed_at: int
    placeholder_salt: str


def _validate_name(name: str) -> None:
    if not _VALID_NAME_RE.fullmatch(name):
        raise InvalidProjectName(
            f"invalid project name: must match {_VALID_NAME_RE.pattern}"
        )


_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    last_accessed_at INTEGER NOT NULL,
    placeholder_salt TEXT NOT NULL DEFAULT ''
);
"""


class ProjectRegistry:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, db_path: Path) -> "ProjectRegistry":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_DDL)
        return cls(conn)

    def close(self) -> None:
        self._conn.close()

    def create(
        self,
        name: str,
        description: str = "",
        placeholder_salt: str | None = None,
    ) -> ProjectInfo:
        _validate_name(name)
        if self.exists(name):
            raise ValueError(f"project '{name}' already exists")
        salt = name if placeholder_salt is None else placeholder_salt
        now = int(time.time())
        self._conn.execute(
            "INSERT INTO projects (name, description, created_at, last_accessed_at, placeholder_salt) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, description, now, now, salt),
        )
        return ProjectInfo(
            name=name,
            description=description,
            created_at=now,
            last_accessed_at=now,
            placeholder_salt=salt,
        )

    def get(self, name: str) -> ProjectInfo | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_info(row)

    def exists(self, name: str) -> bool:
        return self.get(name) is not None

    def list(self) -> list[ProjectInfo]:
        rows = self._conn.execute(
            "SELECT * FROM projects ORDER BY last_accessed_at DESC"
        ).fetchall()
        return [self._row_to_info(r) for r in rows]

    def delete(self, name: str) -> bool:
        cur = self._conn.execute("DELETE FROM projects WHERE name = ?", (name,))
        return cur.rowcount > 0

    def touch(self, name: str) -> None:
        self._conn.execute(
            "UPDATE projects SET last_accessed_at = ? WHERE name = ?",
            (int(time.time()), name),
        )

    @staticmethod
    def _row_to_info(row: sqlite3.Row) -> ProjectInfo:
        return ProjectInfo(
            name=row["name"],
            description=row["description"],
            created_at=row["created_at"],
            last_accessed_at=row["last_accessed_at"],
            placeholder_salt=row["placeholder_salt"],
        )
