"""`piighost init` — create `.piighost/` in the current directory."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from piighost.cli.output import ExitCode, emit_error_line, emit_json_line

_DEFAULT_CONFIG = """\
schema_version = 1

[vault]
placeholder_factory = "hash"
audit_log = true

[detector]
backend = "gliner2"
gliner2_model = "fastino/gliner2-base-v1"
gliner2_adapter = "jamon8888/french-pii-legal-ner-base"
threshold = 0.5
labels = ["PERSON", "LOC", "ORG", "EMAIL", "PHONE", "IBAN", "CREDIT_CARD", "ID"]

[embedder]
# "local" gives semantic vector search out of the box (downloads Solon ~1.1GB
# from HuggingFace on first use). Set to "none" for BM25-only indexing.
backend = "local"
local_model = "OrdalieTech/Solon-embeddings-base-0.1"

[index]
store = "lancedb"
chunk_size = 512
chunk_overlap = 64
bm25_weight = 0.4
vector_weight = 0.6

[reranker]
backend = "none"

[daemon]
idle_timeout_sec = 3600

[safety]
strict_rehydrate = true
max_doc_bytes = 10485760
redact_errors = true
"""


def run(force: bool = typer.Option(False, "--force")) -> None:
    from piighost.vault.store import Vault

    cwd = Path(os.environ.get("PIIGHOST_CWD", Path.cwd()))
    vault_dir = cwd / ".piighost"
    cfg = vault_dir / "config.toml"
    if vault_dir.exists() and not force:
        emit_error_line(
            error="VaultAlreadyExists",
            message=f"{vault_dir} already exists",
            hint="pass --force to overwrite",
            exit_code=ExitCode.USER_ERROR,
        )
        raise typer.Exit(code=int(ExitCode.USER_ERROR))
    vault_dir.mkdir(parents=True, exist_ok=True)
    cfg.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    # Pre-create the DB so second-call users get a warm schema.
    v = Vault.open(vault_dir / "vault.db")
    v.close()
    emit_json_line({"created": str(vault_dir), "config": str(cfg)})
