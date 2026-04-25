"""Anonymize POST /v1/messages requests and rehydrate streamed responses."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

from mitmproxy.http import Response

from piighost.proxy.forward.handlers.base import Handler
from piighost.proxy.forward.sse import SSEEvent, parse_sse_chunks, rebuild_sse_chunk

if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow


class _Service(Protocol):
    async def anonymize(self, text: str, *, project: str) -> tuple[str, dict[str, Any]]: ...
    async def rehydrate(self, text: str, *, project: str) -> str: ...
    async def active_project(self) -> str: ...


class MessagesHandler(Handler):
    """Anonymize text and system fields in POST /v1/messages."""

    def __init__(self, *, service: _Service) -> None:
        self._service = service

    async def handle_request(self, flow: "HTTPFlow") -> None:
        try:
            body = json.loads(flow.request.content)
        except (TypeError, json.JSONDecodeError):
            flow.response = Response.make(
                400,
                json.dumps({"error": "piighost: invalid JSON body"}).encode("utf-8"),
                {"content-type": "application/json"},
            )
            return

        try:
            project = await self._service.active_project()
            await self._anonymize_messages(body.get("messages", []), project=project)
            await self._anonymize_system(body, project=project)
        except Exception as exc:
            flow.response = Response.make(
                503,
                json.dumps({
                    "error": f"piighost: anonymization failed: {exc}",
                    "type": "piighost_unavailable",
                }).encode("utf-8"),
                {"content-type": "application/json"},
            )
            return

        flow.request.content = json.dumps(body).encode("utf-8")

    async def handle_response(self, flow: "HTTPFlow") -> None:
        if flow.response is None:
            return
        ctype = flow.response.headers.get("content-type", "")
        if "text/event-stream" not in ctype:
            return  # Phase 2: non-stream JSON rehydration

        try:
            project = await self._service.active_project()
            flow.response.content = await self._rehydrate_sse(
                flow.response.content, project=project
            )
        except Exception:
            return  # rehydration unavailable; placeholders remain but no PII is leaked

    async def _rehydrate_sse(self, raw: bytes, *, project: str) -> bytes:
        out = bytearray()
        for event in parse_sse_chunks(raw):
            try:
                payload = json.loads(event.data)
            except (TypeError, json.JSONDecodeError):
                out.extend(rebuild_sse_chunk(event))
                continue
            await self._rehydrate_event_payload(payload, project=project)
            out.extend(
                rebuild_sse_chunk(SSEEvent(event=event.event, data=json.dumps(payload)))
            )
        return bytes(out)

    async def _rehydrate_event_payload(self, payload: dict, *, project: str) -> None:
        delta = payload.get("delta") or {}
        if isinstance(delta, dict) and delta.get("type") == "text_delta":
            text = delta.get("text", "")
            delta["text"] = await self._service.rehydrate(text, project=project)

    async def _anonymize_messages(self, messages: list[dict], *, project: str) -> None:
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                msg["content"], _ = await self._service.anonymize(content, project=project)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        block["text"], _ = await self._service.anonymize(text, project=project)
                    # image / document / tool_use / tool_result handled in Phase 2

    async def _anonymize_system(self, body: dict, *, project: str) -> None:
        system = body.get("system")
        if isinstance(system, str):
            body["system"], _ = await self._service.anonymize(system, project=project)
        elif isinstance(system, list):
            for block in system:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    block["text"], _ = await self._service.anonymize(text, project=project)
