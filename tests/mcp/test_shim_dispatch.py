"""Shim HTTP forwarder: maps ToolSpec calls to daemon /rpc."""
from __future__ import annotations

import json

import httpx
import pytest

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
