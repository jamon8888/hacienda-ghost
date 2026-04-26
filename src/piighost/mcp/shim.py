"""Thin stdio→HTTP shim for piighost MCP.

The shim exposes the same MCP tools as before but does no work itself —
every call is forwarded to the singleton ``piighost daemon`` over
loopback HTTP.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastmcp import FastMCP

from piighost.daemon.audit_log import emit
from piighost.daemon.lifecycle import ensure_daemon
from piighost.mcp.tools import TOOL_CATALOG, ToolSpec


class RpcError(RuntimeError):
    """Raised when a daemon RPC call fails (HTTP, timeout, or JSON-RPC error)."""


async def dispatch(
    spec: ToolSpec,
    *,
    params: dict,
    base_url: str,
    token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Forward one MCP tool call to the daemon's /rpc endpoint.

    Returns the daemon's ``result`` field on success.
    Raises :class:`RpcError` on:
      - JSON-RPC error response (with the daemon's error message)
      - HTTP non-2xx
      - Read/connect timeout (per the spec's ``timeout_s``)
      - Any other transport failure

    The shim NEVER retries silently; surfacing failures is the only way
    to notice the daemon is unhealthy.
    """
    body = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": spec.rpc_method,
        "params": params,
    }
    timeout = httpx.Timeout(spec.timeout_s, connect=5.0)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            r = await client.post(
                f"{base_url}/rpc",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.TimeoutException as exc:
        raise RpcError(f"{spec.name} timed out after {spec.timeout_s}s") from exc
    except httpx.HTTPError as exc:
        raise RpcError(f"{spec.name} transport error: {exc}") from exc

    if r.status_code != 200:
        raise RpcError(f"{spec.name} HTTP {r.status_code}: {r.text[:200]}")

    payload = r.json()
    if "error" in payload:
        msg = payload["error"].get("message", "unknown")
        raise RpcError(f"{spec.name}: {msg}")
    return payload.get("result", {})


def _build_mcp(*, vault_dir) -> FastMCP:
    """Construct a FastMCP server with one tool per catalog entry.

    Each tool has an explicit signature matching its daemon RPC method,
    so MCP clients see the right parameter schema.

    Daemon connection is lazy: we DO NOT block startup on
    ``ensure_daemon``. The MCP ``initialize`` and ``tools/list``
    handshake completes immediately so MCP clients (Claude Desktop)
    don't time out (~22s) on a cold daemon spawn (~15s on Windows).
    The first actual tool invocation pays the spawn cost; subsequent
    calls are instant.
    """
    import asyncio

    mcp = FastMCP("piighost")
    by_name = {s.name: s for s in TOOL_CATALOG}

    # Shared mutable state populated on first dispatch.
    _conn: dict[str, str | None] = {"base_url": None, "token": None}
    _lock = asyncio.Lock()

    async def _ensure() -> None:
        """Spawn/connect to the daemon on first tool dispatch."""
        if _conn["base_url"] is not None:
            return
        async with _lock:
            if _conn["base_url"] is not None:
                return  # double-checked: another task did it while we waited
            hs = await asyncio.to_thread(ensure_daemon, vault_dir)
            _conn["base_url"] = f"http://127.0.0.1:{hs.port}"
            _conn["token"] = hs.token
            emit(vault_dir / "daemon.log", "shim_started", daemon_pid=hs.pid)

    async def _lazy_dispatch(spec: ToolSpec, *, params: dict) -> dict:
        await _ensure()
        try:
            return await dispatch(
                spec,
                params=params,
                base_url=_conn["base_url"],
                token=_conn["token"],
            )
        except RpcError as exc:
            # The cached connection points at a daemon that's gone or
            # rotated (handshake refresh). Invalidate and retry once
            # so callers don't have to restart the shim.
            msg = str(exc)
            if "transport error" not in msg and "HTTP " not in msg:
                raise
            async with _lock:
                _conn["base_url"] = None
                _conn["token"] = None
            await _ensure()
            return await dispatch(
                spec,
                params=params,
                base_url=_conn["base_url"],
                token=_conn["token"],
            )

    # ------------------------------------------------------------------
    # Core PII operations
    # ------------------------------------------------------------------

    @mcp.tool(name="anonymize_text", description=by_name["anonymize_text"].description)
    async def anonymize_text(text: str, doc_id: str = "", project: str = "default") -> dict:
        return await _lazy_dispatch(
            by_name["anonymize_text"],
            params={"text": text, "doc_id": doc_id, "project": project},
        )

    @mcp.tool(name="rehydrate_text", description=by_name["rehydrate_text"].description)
    async def rehydrate_text(text: str, project: str = "default") -> dict:
        return await _lazy_dispatch(
            by_name["rehydrate_text"],
            params={"text": text, "project": project},
        )

    @mcp.tool(name="detect", description=by_name["detect"].description)
    async def detect(text: str, project: str = "default") -> dict:
        # Daemon RPC returns list[Detection-shaped-dict]; FastMCP requires
        # a dict for structured content. Wrap.
        result = await _lazy_dispatch(
            by_name["detect"],
            params={"text": text, "project": project},
        )
        if isinstance(result, list):
            return {"detections": result}
        return result

    # ------------------------------------------------------------------
    # Vault inspection
    # ------------------------------------------------------------------

    @mcp.tool(name="vault_list", description=by_name["vault_list"].description)
    async def vault_list(
        label: str = "",
        limit: int = 100,
        offset: int = 0,
        reveal: bool = False,
        project: str = "default",
    ) -> dict:
        return await _lazy_dispatch(
            by_name["vault_list"],
            params={
                "label": label,
                "limit": limit,
                "offset": offset,
                "reveal": reveal,
                "project": project,
            },
        )

    @mcp.tool(name="vault_show", description=by_name["vault_show"].description)
    async def vault_show(
        token: str, reveal: bool = False, project: str = "default"
    ) -> dict:
        return await _lazy_dispatch(
            by_name["vault_show"],
            params={"token": token, "reveal": reveal, "project": project},
        )

    @mcp.tool(name="vault_stats", description=by_name["vault_stats"].description)
    async def vault_stats(project: str = "default") -> dict:
        return await _lazy_dispatch(
            by_name["vault_stats"],
            params={"project": project},
        )

    @mcp.tool(name="vault_search", description=by_name["vault_search"].description)
    async def vault_search(
        query: str, reveal: bool = False, limit: int = 100, project: str = "default"
    ) -> dict:
        # Daemon RPC returns list[VaultEntry-shaped-dict]; FastMCP requires
        # a dict for structured content. Wrap.
        result = await _lazy_dispatch(
            by_name["vault_search"],
            params={"query": query, "reveal": reveal, "limit": limit, "project": project},
        )
        if isinstance(result, list):
            return {"entries": result}
        return result

    # ------------------------------------------------------------------
    # RAG indexing & query
    # ------------------------------------------------------------------

    @mcp.tool(name="index_path", description=by_name["index_path"].description)
    async def index_path(
        path: str,
        recursive: bool = True,
        force: bool = False,
        project: str = "",
    ) -> dict:
        return await _lazy_dispatch(
            by_name["index_path"],
            params={"path": path, "recursive": recursive, "force": force, "project": project},
        )

    @mcp.tool(name="remove_doc", description=by_name["remove_doc"].description)
    async def remove_doc(path: str, project: str = "default") -> dict:
        return await _lazy_dispatch(
            by_name["remove_doc"],
            params={"path": path, "project": project},
        )

    @mcp.tool(name="index_status", description=by_name["index_status"].description)
    async def index_status(
        limit: int = 100, offset: int = 0, project: str = "default"
    ) -> dict:
        return await _lazy_dispatch(
            by_name["index_status"],
            params={"limit": limit, "offset": offset, "project": project},
        )

    @mcp.tool(name="query", description=by_name["query"].description)
    async def query(
        text: str,
        k: int = 5,
        project: str = "default",
        filter_prefix: str = "",
        filter_doc_ids: list[str] | None = None,
        rerank: bool = False,
        top_n: int = 20,
    ) -> dict:
        params: dict = {
            "text": text,
            "k": k,
            "project": project,
            "rerank": rerank,
            "top_n": top_n,
        }
        if filter_prefix or filter_doc_ids:
            params["filter"] = {
                "file_path_prefix": filter_prefix or None,
                "doc_ids": list(filter_doc_ids) if filter_doc_ids else [],
            }
        return await _lazy_dispatch(
            by_name["query"],
            params=params,
        )

    # ------------------------------------------------------------------
    # Project management
    # ------------------------------------------------------------------

    @mcp.tool(name="list_projects", description=by_name["list_projects"].description)
    async def list_projects() -> dict:
        # Daemon's RPC returns a list[ProjectInfo-shaped-dict]; FastMCP's
        # structured-content validator requires a dict. Wrap it.
        result = await _lazy_dispatch(
            by_name["list_projects"],
            params={},
        )
        if isinstance(result, list):
            return {"projects": result}
        return result

    @mcp.tool(name="create_project", description=by_name["create_project"].description)
    async def create_project(name: str, description: str = "") -> dict:
        return await _lazy_dispatch(
            by_name["create_project"],
            params={"name": name, "description": description},
        )

    @mcp.tool(name="delete_project", description=by_name["delete_project"].description)
    async def delete_project(name: str, force: bool = False) -> dict:
        return await _lazy_dispatch(
            by_name["delete_project"],
            params={"name": name, "force": force},
        )

    return mcp


async def run(vault_dir) -> None:
    """Entry point: serve MCP over stdio. Daemon is connected lazily on
    first tool invocation so the MCP initialize handshake completes
    fast and the client doesn't time out on cold daemon spawn."""
    from pathlib import Path
    vault_dir = Path(vault_dir)

    log_path = vault_dir / "daemon.log"
    mcp = _build_mcp(vault_dir=vault_dir)
    try:
        await mcp.run_stdio_async()
    finally:
        emit(log_path, "shim_stopped")
