"""Pydantic result types for service-layer operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
        "heuristic_detected", "none",
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


class SubjectDocumentRef(BaseModel):
    """One document reference in a subject_access or forget report."""
    doc_id: str
    file_name: str
    file_path: str
    doc_type: str = "autre"
    doc_date: int | None = None
    occurrences: int = 0  # total times any cluster token appears in this doc
    first_indexed: int | None = None
    last_indexed: int | None = None


class SubjectExcerpt(BaseModel):
    """Redacted excerpt where the subject appears."""
    doc_id: str
    file_name: str
    chunk_index: int
    redacted_text: str  # cluster tokens replaced by <<SUBJECT>> for clarity
    surrounding_tokens: list[str] = Field(default_factory=list)


class SubjectAccessReport(BaseModel):
    """Art. 15 right-of-access report.

    Contains everything needed to produce the formal response to a
    data-subject access request: who, what categories, where (docs),
    how (purposes/legal bases), when (retention), with whom (recipients).
    """
    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    generated_at: int
    project: str
    subject_tokens: list[str]
    subject_preview: list[str] = Field(default_factory=list)
    categories_found: dict[str, int] = Field(default_factory=dict)
    documents: list[SubjectDocumentRef] = Field(default_factory=list)
    processing_purpose: str = ""
    legal_basis: str = ""
    retention_period: str = ""
    third_party_recipients: list[str] = Field(default_factory=list)
    transfers_outside_eu: list[str] = Field(default_factory=list)
    excerpts: list[SubjectExcerpt] = Field(default_factory=list)
    excerpts_truncated: bool = False
    total_excerpts: int = 0


class ForgetReport(BaseModel):
    """Art. 17 right-to-be-forgotten outcome.

    Tombstone semantics: token IDs are returned as hashes only — the
    raw tokens are not persisted in the audit log either.
    """
    v: Literal[1] = 1
    dry_run: bool
    tokens_to_purge_hashes: list[str] = Field(default_factory=list)
    chunks_to_rewrite: int = 0
    docs_affected: list[str] = Field(default_factory=list)
    estimated_duration_ms: int | None = None
    actual_duration_ms: int | None = None
    completed_at: int | None = None
    legal_basis: str = ""


# ---- RGPD Phase 2: Registre Art. 30 + DPIA ----


class ControllerInfo(BaseModel):
    """Identity of the data controller (cabinet / structure)."""
    name: str = ""
    profession: str = ""
    bar_or_order_number: str = ""
    address: str = ""
    country: str = "FR"


class DPOInfo(BaseModel):
    """Designated Data Protection Officer."""
    name: str = ""
    email: str = ""
    phone: str = ""


class DataCategoryItem(BaseModel):
    """One row of the registre's 'categories of data' table."""
    label: str
    count: int
    sensitive: bool = False


class RetentionItem(BaseModel):
    """One retention rule applied to a category of doc/data."""
    category: str
    duration: str


class TransferItem(BaseModel):
    """One identified transfer of data outside the EU."""
    destination: str
    recipient: str = ""
    legal_mechanism: str = ""


class SecurityMeasureItem(BaseModel):
    """One technical/organisational security measure."""
    name: str
    auto_detected: bool = False


class DocumentsSummary(BaseModel):
    """Aggregate counts for the documents_meta inventory."""
    total_docs: int = 0
    by_doc_type: dict[str, int] = Field(default_factory=dict)
    by_language: dict[str, int] = Field(default_factory=dict)
    total_pages: int = 0


class ManualFieldHint(BaseModel):
    """A field the avocat must fill manually, with a hint."""
    field: str
    hint: str


class ProcessingRegister(BaseModel):
    """Art. 30 — registre des activités de traitement.

    Auto-built from documents_meta + vault stats + audit log +
    ControllerProfile. Fields the system can't infer are surfaced
    via ``manual_fields`` so the avocat knows what to complete.
    """
    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    generated_at: int
    project: str

    # 1. Identité du responsable
    controller: ControllerInfo = Field(default_factory=ControllerInfo)
    dpo: DPOInfo | None = None

    # 2. Description du traitement
    processing_name: str = ""
    processing_purposes: list[str] = Field(default_factory=list)
    legal_bases: list[str] = Field(default_factory=list)

    # 3. Catégories de personnes concernées (heuristique)
    data_subject_categories: list[str] = Field(default_factory=list)

    # 4. Catégories de données traitées
    data_categories: list[DataCategoryItem] = Field(default_factory=list)
    sensitive_categories_present: list[str] = Field(default_factory=list)

    # 5. Destinataires
    recipients_internal: list[str] = Field(default_factory=list)
    recipients_external: list[str] = Field(default_factory=list)

    # 6. Transferts hors UE
    transfers_outside_eu: list[TransferItem] = Field(default_factory=list)

    # 7. Durées de conservation
    retention_periods: list[RetentionItem] = Field(default_factory=list)

    # 8. Mesures de sécurité
    security_measures: list[SecurityMeasureItem] = Field(default_factory=list)

    # 9. Inventaire docs
    documents_summary: DocumentsSummary = Field(default_factory=DocumentsSummary)

    # 10. À compléter manuellement
    manual_fields: list[ManualFieldHint] = Field(default_factory=list)


class DPIATrigger(BaseModel):
    """One Art. 35.3 or CNIL trigger detected for this project."""
    code: str
    name: str
    matched_evidence: list[str] = Field(default_factory=list)
    severity: Literal["mandatory", "high", "medium", "low"]


class CNILPIAInputs(BaseModel):
    """Pre-filled inputs for the official CNIL PIA software."""
    processing_name: str = ""
    processing_description: str = ""
    data_categories: list[str] = Field(default_factory=list)
    data_subjects: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    legal_bases: list[str] = Field(default_factory=list)
    retention: str = ""
    recipients: list[str] = Field(default_factory=list)
    security_measures: list[str] = Field(default_factory=list)


class DPIAScreening(BaseModel):
    """DPIA-lite screening — does this project require a full DPIA?"""
    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    generated_at: int
    project: str
    data_inventory: dict[str, int] = Field(default_factory=dict)
    triggers: list[DPIATrigger] = Field(default_factory=list)
    verdict: Literal["dpia_required", "dpia_recommended", "dpia_not_required"]
    verdict_explanation: str = ""
    cnil_pia_inputs: CNILPIAInputs = Field(default_factory=CNILPIAInputs)
    cnil_pia_url: str = "https://www.cnil.fr/fr/outil-pia-telechargez-et-installez-le-logiciel-de-la-cnil"


class RenderResult(BaseModel):
    """Outcome of rendering a structured compliance doc to MD/DOCX/PDF."""
    path: str
    format: Literal["md", "docx", "pdf"]
    size_bytes: int = 0
    rendered_at: int
