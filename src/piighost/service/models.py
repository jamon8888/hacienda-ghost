"""Pydantic result types for service-layer operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EntityRef(BaseModel):
    token: str
    label: str
    count: int = 1


class AnonymizeResult(BaseModel):
    doc_id: str
    anonymized: str
    entities: list[EntityRef] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)


class RehydrateResult(BaseModel):
    text: str
    unknown_tokens: list[str] = Field(default_factory=list)


class DetectionResult(BaseModel):
    text: str
    label: str
    start: int
    end: int
    confidence: float | None = None


class VaultEntryModel(BaseModel):
    token: str
    label: str
    original: str | None = None
    original_masked: str | None = None
    confidence: float | None = None
    first_seen_at: int
    last_seen_at: int
    occurrence_count: int


class VaultStatsModel(BaseModel):
    total: int
    by_label: dict[str, int]


class VaultPage(BaseModel):
    entries: list[VaultEntryModel]
    next_cursor: str | None = None


class IndexReport(BaseModel):
    indexed: int
    modified: int = 0
    deleted: int = 0
    skipped: int
    unchanged: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_ms: int
    project: str = "default"


class QueryHit(BaseModel):
    doc_id: str
    file_path: str
    chunk: str
    score: float
    rank: int


class QueryResult(BaseModel):
    query: str
    hits: list[QueryHit]
    k: int


class IndexedFileEntry(BaseModel):
    doc_id: str
    file_path: str
    indexed_at: int
    chunk_count: int


class IndexStatus(BaseModel):
    total_docs: int
    total_chunks: int
    files: list[IndexedFileEntry]


class FileChangeEntry(BaseModel):
    file_path: str
    size: int


class FolderChangesResult(BaseModel):
    folder: str
    project: str
    new: list[FileChangeEntry] = Field(default_factory=list)
    modified: list[FileChangeEntry] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    unchanged_count: int = 0
    tier: str = "empty"   # BatchTier string value


class CancelResult(BaseModel):
    project: str
    cancelled: bool
    files_processed: int = 0
    files_skipped: int = 0


class FolderError(BaseModel):
    """One file-level indexing failure surfaced by ``folder_status``.

    The Python exception class name is intentionally not exposed —
    server logs are the source of truth for individual exceptions.
    Only the bounded ``category`` (one of ``password_protected``,
    ``corrupt``, ``unsupported_format``, ``timeout``, ``other``)
    crosses the service boundary."""

    file_name: str        # basename only — safe for outbound rendering
    file_path: str        # full path — already exposed by index_status
    category: str         # one of the error_taxonomy values
    indexed_at: int       # unix epoch seconds


class DocumentMetadata(BaseModel):
    """Metadata extracted at index time for one document.

    Combines kreuzberg's free metadata (title, authors, dates) with
    project-level semantics (doc_type, dossier_id, parties). Used by
    the RGPD compliance subsystem (Phases 1 + 2).
    """

    doc_id: str
    doc_type: Literal[
        "contrat", "facture", "email", "courrier", "acte_notarie",
        "jugement", "decision_administrative", "attestation",
        "cv", "note_interne", "autre",
    ] = "autre"
    doc_type_confidence: float = 0.0

    doc_date: int | None = None
    doc_date_source: Literal[
        "kreuzberg_creation", "kreuzberg_modified",
        "heuristic_detected", "filename", "none",
    ] = "none"

    # Free metadata from kreuzberg (FLAT in v4.9.4 — not nested under "pdf")
    doc_title: str | None = None
    doc_subject: str | None = None
    doc_authors: list[str] = Field(default_factory=list)
    doc_language: str | None = None
    doc_page_count: int | None = None
    doc_format: str = ""
    is_encrypted_source: bool = False

    # Project semantics
    parties: list[str] = Field(default_factory=list)
    dossier_id: str = ""
    extracted_at: int
