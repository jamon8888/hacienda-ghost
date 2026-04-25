"""Thin stdio→HTTP shim for piighost MCP.

The shim exposes the same MCP tools as before but does no work itself —
every call is forwarded to the singleton ``piighost daemon`` over
loopback HTTP.
"""
from __future__ import annotations

import uuid

import httpx

from piighost.mcp.tools import ToolSpec


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
