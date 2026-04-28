"""Load ``.piighost/config.toml`` into a validated pydantic model."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


class VaultSection(BaseModel):
    placeholder_factory: Literal["hash"] = "hash"
    audit_log: bool = True

    @field_validator("placeholder_factory", mode="before")
    @classmethod
    def _reject_non_hash(cls, v: str) -> str:
        if v != "hash":
            raise ValueError(
                "placeholder_factory must be 'hash' — counter mode is unsupported "
                "because it breaks RAG token determinism across sessions."
            )
        return v


class DetectorSection(BaseModel):
    backend: Literal["gliner2", "regex_only"] = "gliner2"
    # Base GLiNER2 checkpoint. When ``gliner2_adapter`` is set, this is
    # the *base model* the adapter was trained against — the adapter's
    # encoder dimensions must match. fastino/gliner2-base-v1 uses
    # microsoft/deberta-v3-base (768-dim) which matches the
    # jamon8888/french-pii-legal-ner adapters.
    gliner2_model: str = "fastino/gliner2-base-v1"
    # Optional LoRA adapter loaded on top of the base model via
    # ``GLiNER2.load_adapter()``. HuggingFace repo id or local path.
    # When set, the adapter's labels.json (if present) overrides the
    # ``labels`` field below at runtime.
    gliner2_adapter: str | None = "jamon8888/french-pii-legal-ner-base"
    threshold: float = 0.5
    # Default labels — used when no adapter is loaded, or when the
    # adapter has no labels.json.
    labels: list[str] = Field(
        default_factory=lambda: [
            "PERSON", "LOC", "ORG", "EMAIL",
            "PHONE", "IBAN", "CREDIT_CARD", "ID",
        ]
    )
    regex_fallback: bool = False


class EmbedderSection(BaseModel):
    # Default to "local" so a fresh install has working vector search out of the
    # box. "none" disables vectors entirely (search returns 0 results) and was
    # a footgun for new users. Override in config.toml if you explicitly want
    # BM25-only indexing.
    backend: Literal["local", "mistral", "none"] = "local"
    local_model: str = "OrdalieTech/Solon-embeddings-base-0.1"
    mistral_model: str = "mistral-embed"


class RerankerSection(BaseModel):
    # Default to cross_encoder so query results are quality-ranked out of
    # the box. "none" skips reranking (faster but worse top-k ordering).
    backend: Literal["none", "cross_encoder"] = "cross_encoder"
    cross_encoder_model: str = "BAAI/bge-reranker-base"
    top_n: int = 20


class IndexSection(BaseModel):
    store: Literal["lancedb"] = "lancedb"
    chunk_size: int = 512
    chunk_overlap: int = 64
    bm25_weight: float = 0.4
    vector_weight: float = 0.6


class DaemonSection(BaseModel):
    idle_timeout_sec: int = 3600
    log_level: Literal["debug", "info", "warn", "error"] = "info"
    max_workers: int = 4


class SafetySection(BaseModel):
    strict_rehydrate: bool = True
    max_doc_bytes: int = 10_485_760
    redact_errors: bool = True


class IncrementalSection(BaseModel):
    """Tiered batch thresholds for incremental indexing.

    Tiers from the incremental-indexing spec:
      - SMALL  : <= small_max_files AND total size <  small_max_bytes
      - MEDIUM : <= medium_max_files AND total size <= medium_max_bytes
      - LARGE  : anything bigger
    """

    small_max_files: int = 2
    small_max_bytes: int = 5 * 1024 * 1024        # 5 MB
    medium_max_files: int = 10
    medium_max_bytes: int = 50 * 1024 * 1024       # 50 MB


class OpenLegiSection(BaseModel):
    """Optional OpenLégi (Legifrance) integration."""
    enabled: bool = False
    base_url: str = "https://mcp.openlegi.fr"
    service: Literal["legifrance", "inpi", "eurlex"] = "legifrance"


class ServiceConfig(BaseModel):
    schema_version: int = 1
    vault: VaultSection = Field(default_factory=VaultSection)
    detector: DetectorSection = Field(default_factory=DetectorSection)
    embedder: EmbedderSection = Field(default_factory=EmbedderSection)
    reranker: RerankerSection = Field(default_factory=RerankerSection)
    index: IndexSection = Field(default_factory=IndexSection)
    daemon: DaemonSection = Field(default_factory=DaemonSection)
    safety: SafetySection = Field(default_factory=SafetySection)
    incremental: IncrementalSection = Field(default_factory=IncrementalSection)
    openlegi: OpenLegiSection = Field(default_factory=OpenLegiSection)

    @classmethod
    def from_toml(cls, path: Path) -> "ServiceConfig":
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data)

    @classmethod
    def default(cls) -> "ServiceConfig":
        return cls()
