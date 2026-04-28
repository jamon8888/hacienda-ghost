"""PisteClient — sync httpx wrapper for the OpenLégi MCP endpoint.

Ported from the OpenLégi documentation example. Differences from
the docs version:
  - httpx (already a base dep) instead of requests
  - 10s connect / 30s read timeout — never block the daemon
  - 429 retries with exponential backoff + jitter, max 3 attempts
  - Context-manager lifecycle (no module-level singleton)
"""
from __future__ import annotations

import json
import random
import time
from typing import Any

import httpx


class PisteClient:
    """Sync wrapper for OpenLégi's MCP-over-HTTPS endpoint."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://mcp.openlegi.fr",
        service: str = "legifrance",
        timeout_connect: float = 10.0,
        timeout_read: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._service = service
        self._max_retries = max_retries
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=timeout_connect, read=timeout_read,
                                  write=10.0, pool=10.0),
            follow_redirects=False,
        )
        self._next_id = 1
        self._session_id: str | None = None

    def __enter__(self) -> "PisteClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def _url(self) -> str:
        return f"{self._base_url}/{self._service}"

    @property
    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Invoke ``tool_name`` with ``arguments`` and return its result."""
        rid = self._next_id
        self._next_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        return self._post_with_retry(body)

    def list_tools(self) -> list[dict]:
        rid = self._next_id
        self._next_id += 1
        body = {"jsonrpc": "2.0", "id": rid, "method": "tools/list"}
        result = self._post_with_retry(body)
        return result.get("tools", [])

    def _post_with_retry(self, body: dict) -> dict:
        attempt = 0
        while True:
            try:
                resp = self._client.post(self._url, json=body, headers=self._headers)
            except httpx.RequestError as exc:
                # Transient: DNS / conn reset / timeout. Retry with the
                # same backoff schedule as 429.
                if attempt < self._max_retries:
                    attempt += 1
                    delay = 0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    time.sleep(delay)
                    continue
                raise
            if resp.status_code == 429 and attempt < self._max_retries:
                attempt += 1
                # Exponential backoff with jitter: 0.5s, 1s, 2s + [0, 0.5)
                delay = 0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return self._parse_sse(resp.text)

    @staticmethod
    def _parse_sse(text: str) -> dict:
        """Parse one OpenLégi SSE event and return its result payload.

        Format::
            event: message
            data: {"jsonrpc":"2.0","id":1,"result":{...}}
            \\n\\n
        """
        lines = text.strip().splitlines()
        for line in lines:
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"SSE parse error: {exc}") from exc
                if "error" in parsed and parsed["error"]:
                    raise ValueError(f"OpenLégi error: {parsed['error']}")
                return parsed.get("result", {})
        raise ValueError("SSE parse error: no data: line found")
