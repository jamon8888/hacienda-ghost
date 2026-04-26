"""Shim HTTP forwarder: maps ToolSpec calls to daemon /rpc."""
from __future__ import annotations

import json

import httpx
import pytest

pytest.importorskip('fastmcp')

from piighost.mcp.shim import RpcError, dispatch
from piighost.mcp.tools import ToolSpec


SAMPLE_SPEC = ToolSpec(
    name="anonymize_text",
    rpc_method="anonymize",
    description="...",
    timeout_s=60.0,
)


def _ok_handler(want_method: str, want_params: dict, response_result: dict):
    def _h(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == want_method
        assert body["params"] == want_params
        assert request.headers["authorization"] == "Bearer abc"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": response_result})
    return _h


@pytest.mark.asyncio
async def test_dispatch_forwards_method_and_params() -> None:
    transport = httpx.MockTransport(_ok_handler(
        "anonymize",
        {"text": "hi", "project": "default"},
        {"anonymized": "<X:1>", "entities": []},
    ))
    result = await dispatch(
        SAMPLE_SPEC,
        params={"text": "hi", "project": "default"},
        base_url="http://127.0.0.1:51207",
        token="abc",
        transport=transport,
    )
    assert result == {"anonymized": "<X:1>", "entities": []}


@pytest.mark.asyncio
async def test_dispatch_raises_on_jsonrpc_error() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0",
            "id": body["id"],
            "error": {"code": -32000, "message": "vault corrupted"},
        })
    with pytest.raises(RpcError, match="vault corrupted"):
        await dispatch(
            SAMPLE_SPEC, params={}, base_url="http://x", token="t",
            transport=httpx.MockTransport(_h),
        )


@pytest.mark.asyncio
async def test_dispatch_raises_on_http_5xx() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")
    with pytest.raises(RpcError, match="HTTP 500"):
        await dispatch(
            SAMPLE_SPEC, params={}, base_url="http://x", token="t",
            transport=httpx.MockTransport(_h),
        )


@pytest.mark.asyncio
async def test_dispatch_raises_on_timeout() -> None:
    fast = ToolSpec(name="x", rpc_method="m", description="d", timeout_s=0.001)

    def _h(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)
    with pytest.raises(RpcError, match=r"timed out"):
        await dispatch(
            fast, params={}, base_url="http://x", token="t",
            transport=httpx.MockTransport(_h),
        )


@pytest.mark.asyncio
async def test_dispatch_uses_per_tool_timeout() -> None:
    captured: dict = {}
    def _h(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"jsonrpc":"2.0","id":1,"result":{}})
    long = ToolSpec(name="x", rpc_method="m", description="d", timeout_s=600.0)
    await dispatch(
        long, params={}, base_url="http://x", token="t",
        transport=httpx.MockTransport(_h),
    )
    # The httpx Timeout object embeds 600.0 as the read timeout
    assert captured["timeout"]["read"] == 600.0


@pytest.mark.asyncio
async def test_each_tool_has_explicit_kwargs(tmp_path, monkeypatch) -> None:
    """Regression: every registered tool must have explicit named parameters,
    not a single `params: dict`. This is what gives MCP clients a useful
    parameter schema instead of a black box."""
    from piighost.mcp.shim import _build_mcp
    # Schema inspection only — tools never invoked, so daemon is never spawned.
    mcp = _build_mcp(vault_dir=tmp_path)
    tools = await mcp.list_tools()
    assert len(tools) == 14, f"Expected 14 tools, got {len(tools)}"
    for tool in tools:
        props = list(tool.parameters.get("properties", {}).keys())
        assert "params" not in props or len(props) > 1, (
            f"{tool.name} accepts a generic `params: dict` instead of explicit kwargs"
        )


@pytest.mark.asyncio
async def test_vault_show_uses_daemon_auth_token_not_param(tmp_path) -> None:
    """Regression: vault_show accepts a `token` parameter (vault placeholder).
    That must NOT be sent as the Authorization bearer — the daemon's
    bearer token from the closure must be used."""
    captured: dict = {}

    def _h(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        body = json.loads(request.content)
        captured["params"] = body["params"]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    from piighost.mcp.shim import _build_mcp
    import httpx as _httpx
    transport = _httpx.MockTransport(_h)

    import piighost.mcp.shim as shim
    from piighost.daemon.handshake import DaemonHandshake
    fake_hs = DaemonHandshake(pid=1, port=51207, token="DAEMON_BEARER", started_at=0)
    original = _httpx.AsyncClient
    def _make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)
    import unittest.mock
    with unittest.mock.patch.object(_httpx, "AsyncClient", _make_client), \
         unittest.mock.patch.object(shim, "ensure_daemon", lambda vault_dir: fake_hs):
        mcp = _build_mcp(vault_dir=tmp_path)
        vault_show_tool = await mcp.get_tool("vault_show")
        await vault_show_tool.fn(token="<PERSON:abc>", reveal=False, project="default")

    assert captured["auth"] == "Bearer DAEMON_BEARER", (
        f"vault_show sent wrong auth header: {captured['auth']!r}"
    )
    assert captured["params"]["token"] == "<PERSON:abc>"


@pytest.mark.asyncio
async def test_query_sends_nested_filter_to_daemon(tmp_path) -> None:
    """Regression: shim must wrap filter_prefix/filter_doc_ids in a nested
    `filter` object that matches the daemon's reader."""
    captured: dict = {}

    def _h(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["params"] = body["params"]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"hits": []}})

    from piighost.mcp.shim import _build_mcp
    import piighost.mcp.shim as shim
    from piighost.daemon.handshake import DaemonHandshake
    fake_hs = DaemonHandshake(pid=1, port=51207, token="t", started_at=0)
    import httpx as _httpx
    transport = _httpx.MockTransport(_h)
    import unittest.mock
    original = _httpx.AsyncClient
    def _make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)
    with unittest.mock.patch.object(_httpx, "AsyncClient", _make_client), \
         unittest.mock.patch.object(shim, "ensure_daemon", lambda vault_dir: fake_hs):
        mcp = _build_mcp(vault_dir=tmp_path)
        query_tool = await mcp.get_tool("query")
        await query_tool.fn(
            text="hi",
            filter_prefix="docs/",
            filter_doc_ids=["doc1", "doc2"],
        )

    assert "filter" in captured["params"], "shim must nest filter, not flatten"
    assert captured["params"]["filter"]["file_path_prefix"] == "docs/"
    assert captured["params"]["filter"]["doc_ids"] == ["doc1", "doc2"]
    assert "filter_prefix" not in captured["params"]
    assert "filter_doc_ids" not in captured["params"]
