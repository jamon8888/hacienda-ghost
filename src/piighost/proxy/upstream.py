"""Thin async httpx client for forwarding to api.anthropic.com.

Kept isolated so tests can substitute a MockTransport.
"""
from __future__ import annotations

from typing import Any

import httpx


class AnthropicUpstream:
    def __init__(
        self,
        *,
        base_url: str = "https://api.anthropic.com",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 600.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
        )

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        req = self._client.build_request("POST", path, json=json, headers=headers)
        return await self._client.send(req, stream=True)

    async def aclose(self) -> None:
        await self._client.aclose()
