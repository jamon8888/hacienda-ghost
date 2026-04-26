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
    gliner2_model: str = "jamon8888/french-pii-legal-ner-quantized"
    threshold: float = 0.5
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
    backend: Literal["none", "cross_encoder"] = "none"
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

    @classmethod
    def from_toml(cls, path: Path) -> "ServiceConfig":
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data)

    @classmethod
    def default(cls) -> "ServiceConfig":
        return cls()
