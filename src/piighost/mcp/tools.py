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
]
