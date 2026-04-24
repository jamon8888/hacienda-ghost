from __future__ import annotations

import pytest
import httpx

from piighost.proxy.upstream import AnthropicUpstream


@pytest.mark.asyncio
async def test_forward_headers_preserved() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    upstream = AnthropicUpstream(base_url="https://api.anthropic.com", transport=transport)
    resp = await upstream.post(
        "/v1/messages",
        json={"model": "x"},
        headers={"authorization": "Bearer sk-test", "anthropic-version": "2023-06-01"},
    )
    await resp.aclose() if hasattr(resp, "aclose") else None
    assert seen["headers"]["authorization"] == "Bearer sk-test"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"


@pytest.mark.asyncio
async def test_forwards_to_default_base_url() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    upstream = AnthropicUpstream(base_url="https://api.anthropic.com", transport=transport)
    await upstream.post("/v1/messages", json={})
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
