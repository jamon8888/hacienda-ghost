"""Retrieval-time filters for svc.query()."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueryFilter:
    file_path_prefix: str | None = None
    doc_ids: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        return self.file_path_prefix is None and not self.doc_ids

    def to_lance_where(self) -> str | None:
        clauses: list[str] = []
        if self.file_path_prefix:
            escaped = self.file_path_prefix.replace("'", "''")
            clauses.append(f"file_path LIKE '{escaped}%'")
        if self.doc_ids:
            ids = ", ".join(f"'{d}'" for d in self.doc_ids)
            clauses.append(f"doc_id IN ({ids})")
        return " AND ".join(clauses) if clauses else None

    def matches(self, doc_id: str, file_path: str) -> bool:
        if self.file_path_prefix and not file_path.startswith(self.file_path_prefix):
            return False
        if self.doc_ids and doc_id not in self.doc_ids:
            return False
        return True
