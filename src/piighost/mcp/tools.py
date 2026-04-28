"""MCP tool catalog: maps each public tool name to a daemon RPC method.

The shim iterates this list to register one FastMCP tool per entry.
Each tool's HTTP timeout is sized for the operation; ``index_path`` is
the largest at 10 minutes because indexing a multi-format folder can
take that long.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    """One MCP tool exposed by the shim."""

    name: str          # public name shown to MCP clients
    rpc_method: str    # daemon /rpc method this forwards to
    description: str   # human description for the MCP tool
    timeout_s: float   # HTTP timeout for the forward call


TOOL_CATALOG: list[ToolSpec] = [
    # Core PII operations
    ToolSpec(
        name="anonymize_text",
        rpc_method="anonymize",
        description="Anonymize text, replacing PII with opaque tokens.",
        timeout_s=60.0,
    ),
    ToolSpec(
        name="rehydrate_text",
        rpc_method="rehydrate",
        description="Rehydrate anonymized text back to original PII.",
        timeout_s=60.0,
    ),
    ToolSpec(
        name="detect",
        rpc_method="detect",
        description="Detect PII entities without modifying the text.",
        timeout_s=60.0,
    ),

    # Vault inspection
    ToolSpec(
        name="vault_list",
        rpc_method="vault_list",
        description="List vault entries with optional label filter.",
        timeout_s=5.0,
    ),
    ToolSpec(
        name="vault_show",
        rpc_method="vault_show",
        description="Show one vault entry by token.",
        timeout_s=5.0,
    ),
    ToolSpec(
        name="vault_stats",
        rpc_method="vault_stats",
        description="Return vault statistics (total, by label).",
        timeout_s=5.0,
    ),
    ToolSpec(
        name="vault_search",
        rpc_method="vault_search",
        description="Full-text search the PII vault by original value.",
        timeout_s=60.0,
    ),

    # RAG indexing & query
    ToolSpec(
        name="index_path",
        rpc_method="index_path",
        description="Index a file or directory into the retrieval store.",
        timeout_s=600.0,
    ),
    ToolSpec(
        name="remove_doc",
        rpc_method="remove_doc",
        description="Remove a document from the retrieval store.",
        timeout_s=30.0,
    ),
    ToolSpec(
        name="index_status",
        rpc_method="index_status",
        description="Show what is currently indexed.",
        timeout_s=600.0,
    ),
    ToolSpec(
        name="query",
        rpc_method="query",
        description="Hybrid BM25+vector search over indexed documents.",
        timeout_s=60.0,
    ),

    # Project management
    ToolSpec(
        name="list_projects",
        rpc_method="list_projects",
        description="List all projects.",
        timeout_s=5.0,
    ),
    ToolSpec(
        name="create_project",
        rpc_method="create_project",
        description="Create a new project.",
        timeout_s=30.0,
    ),
    ToolSpec(
        name="delete_project",
        rpc_method="delete_project",
        description="Delete a project (requires force=True for non-empty).",
        timeout_s=30.0,
    ),

    # Folder/project resolution + audit (used by the hacienda Cowork plugin)
    ToolSpec(
        name="resolve_project_for_folder",
        rpc_method="resolve_project_for_folder",
        description="Derive the project name for a filesystem folder.",
        timeout_s=5.0,
    ),
    ToolSpec(
        name="bootstrap_client_folder",
        rpc_method="bootstrap_client_folder",
        description="Idempotently ensure the project for a folder exists.",
        timeout_s=30.0,
    ),
    ToolSpec(
        name="folder_status",
        rpc_method="folder_status",
        description=(
            "Indexing status for a folder: state, total_docs, "
            "total_chunks, last_indexed_at, errors[], errors_truncated, "
            "total_errors. Replaces the piighost://folders/{b64}/status "
            "resource — much more reliable than templated resources "
            "across MCP clients."
        ),
        timeout_s=10.0,
    ),
    ToolSpec(
        name="session_audit_read",
        rpc_method="session_audit_read",
        description="Read a session's (=project's) audit log.",
        timeout_s=10.0,
    ),
    ToolSpec(
        name="session_audit_append",
        rpc_method="session_audit_append",
        description="Append an event to a session's (=project's) audit log.",
        timeout_s=5.0,
    ),

    # RGPD Phase 1 — Droits Art. 15 + Art. 17
    ToolSpec(
        name="cluster_subjects",
        rpc_method="cluster_subjects",
        description=(
            "Find probable subject clusters for a free-text query "
            "(person name, email, etc.). Returns groups of co-occurring "
            "PII tokens — the avocat validates which cluster to apply "
            "to subject_access or forget_subject."
        ),
        timeout_s=15.0,
    ),
    ToolSpec(
        name="subject_access",
        rpc_method="subject_access",
        description=(
            "Art. 15 right-of-access report. Returns all documents + "
            "redacted excerpts where the subject (cluster of tokens) "
            "appears, plus controller context (purpose, legal basis, "
            "retention)."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="forget_subject",
        rpc_method="forget_subject",
        description=(
            "Art. 17 right-to-be-forgotten with tombstone. dry_run=True "
            "by default — preview the cascade. dry_run=False purges "
            "vault entries and rewrites chunks with <<deleted:HASH>>; "
            "audit event 'forgotten' carries token hashes only."
        ),
        timeout_s=120.0,  # re-embedding is the slowest path
    ),

    # Controller profile (RGPD compliance — Phase 0 surface, exposed in Phase 2)
    ToolSpec(
        name="controller_profile_get",
        rpc_method="controller_profile_get",
        description=(
            "Read the data controller profile (cabinet/profession/DPO/"
            "purposes/retention). scope='global' returns ~/.piighost/"
            "controller.toml; scope='project' returns the merged view "
            "(global + per-project override) for a given project."
        ),
        timeout_s=2.0,
    ),
    ToolSpec(
        name="controller_profile_set",
        rpc_method="controller_profile_set",
        description=(
            "Atomically write the data controller profile. scope='global' "
            "writes ~/.piighost/controller.toml; scope='project' writes a "
            "per-project override containing only the fields that differ."
        ),
        timeout_s=5.0,
    ),
    ToolSpec(
        name="controller_profile_defaults",
        rpc_method="controller_profile_defaults",
        description=(
            "Read-only: return the bundled default profile for a profession "
            "(avocat / notaire / medecin / expert_comptable / rh / generic). "
            "Used by /hacienda:setup to pre-fill finalites, bases_legales, "
            "duree_conservation, and ordinal_label. Returns {} for unknown "
            "profession or invalid input (rejects path traversal via strict "
            "regex on profession)."
        ),
        timeout_s=2.0,
    ),

    # RGPD Phase 2 — Registre Art. 30 + DPIA + Render
    ToolSpec(
        name="processing_register",
        rpc_method="processing_register",
        description=(
            "Generate the Art. 30 register for a project: controller, "
            "DPO, data categories with Art. 9 sensitivity flag, document "
            "inventory, retention, security measures. Auto-built from "
            "documents_meta + vault.stats() + ControllerProfile."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="dpia_screening",
        rpc_method="dpia_screening",
        description=(
            "DPIA-lite screening (Art. 35). Detects triggers, emits "
            "verdict, prepares CNILPIAInputs for the official CNIL PIA "
            "software. Does NOT generate a full DPIA — that's CNIL's tool."
        ),
        timeout_s=15.0,
    ),
    ToolSpec(
        name="render_compliance_doc",
        rpc_method="render_compliance_doc",
        description=(
            "Render a compliance dict (processing_register, dpia_screening, "
            "subject_access_report) to MD/DOCX/PDF using profession-aware "
            "Jinja2 templates. profile='avocat'|'notaire'|'medecin'|"
            "'expert_comptable'|'rh'|'generic'."
        ),
        timeout_s=60.0,
    ),

    # ---- Legal (OpenLégi) ----
    ToolSpec(
        name="extract_legal_refs",
        rpc_method="legal_extract_refs",
        description=(
            "Extract French legal references from text (article codes, "
            "lois, décrets, ordonnances, jurisprudence). Pure-function — "
            "no network, no token required. Returns a list of "
            "LegalReference dicts with sequential ref_id."
        ),
        timeout_s=2.0,
    ),
    ToolSpec(
        name="verify_legal_ref",
        rpc_method="legal_verify_ref",
        description=(
            "Verify one legal reference against OpenLégi (Legifrance). "
            "Returns VerificationResult with status (VERIFIE_EXACT / "
            "HALLUCINATION / UNKNOWN_*) + score 0-100. Returns "
            "UNKNOWN_OPENLEGI_DISABLED if [openlegi].enabled = false."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="search_legal",
        rpc_method="legal_search",
        description=(
            "Search OpenLégi by source: 'code' / 'jurisprudence_judiciaire' "
            "/ 'jurisprudence_administrative' / 'cnil' / 'jorf' / "
            "'lois_decrets' / 'conventions_collectives' / 'auto'. Returns "
            "list of LegalHit. Empty list if OpenLégi disabled or no token."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="legal_passthrough",
        rpc_method="legal_passthrough",
        description=(
            "Power-user escape hatch: invoke any of OpenLégi's 12 raw "
            "tools by name. Outbound payload still passes through the "
            "redactor — no opt-out."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="legal_credentials_set",
        rpc_method="legal_credentials_set",
        description=(
            "Write a PISTE token to ~/.piighost/credentials.toml (chmod "
            "600 on POSIX). The token is NEVER returned by any read "
            "method. Used by /hacienda:legal:setup."
        ),
        timeout_s=5.0,
    ),
]
