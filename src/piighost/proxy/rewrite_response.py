"""Async SSE stream rewriter: rehydrates text_delta and input_json_delta chunks.

Uses a per-content-block StreamBuffer so placeholders split across deltas
survive until complete. See spec §4.2–§4.3.
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Protocol

from piighost.proxy.stream_buffer import StreamBuffer


class Rehydrator(Protocol):
    async def rehydrate(self, text: str, *, project: str) -> str: ...


def _parse_sse(raw: bytes) -> list[tuple[str, dict]]:
    """Parse a possibly multi-event SSE chunk. Returns [(event, data), ...]."""
    events: list[tuple[str, dict]] = []
    for block in raw.split(b"\n\n"):
        if not block.strip():
            continue
        event = ""
        data_lines: list[str] = []
        for line in block.decode("utf-8", errors="replace").splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        data = json.loads("\n".join(data_lines)) if data_lines else {}
        events.append((event, data))
    return events


def _format_sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


async def rewrite_sse_stream(
    upstream: AsyncIterator[bytes],
    rehydrator: Rehydrator,
    *,
    project: str,
) -> AsyncIterator[bytes]:
    """Yield rewritten SSE bytes. One StreamBuffer per content-block index."""
    buffers: dict[int, StreamBuffer] = {}
    block_types: dict[int, str] = {}
    line_buf = b""

    async def _handle_event(event: str, data: dict):
        if event == "content_block_start":
            idx = data.get("index", 0)
            buffers[idx] = StreamBuffer()
            block_types[idx] = data.get("content_block", {}).get("type", "text")
            yield _format_sse(event, data)
        elif event == "content_block_delta":
            idx = data.get("index", 0)
            buf = buffers.setdefault(idx, StreamBuffer())
            delta = data.get("delta", {})
            dtype = delta.get("type")
            if dtype == "text_delta":
                text = delta.get("text", "")
                emitted = buf.feed(text)
                if emitted:
                    rehyd = await rehydrator.rehydrate(emitted, project=project)
                    delta["text"] = rehyd
                    yield _format_sse(event, data)
            elif dtype == "input_json_delta":
                raw = delta.get("partial_json", "")
                emitted = buf.feed(raw)
                if emitted:
                    rehyd = await rehydrator.rehydrate(emitted, project=project)
                    delta["partial_json"] = rehyd
                    yield _format_sse(event, data)
            else:
                yield _format_sse(event, data)
        elif event == "content_block_stop":
            idx = data.get("index", 0)
            buf = buffers.pop(idx, None)
            btype = block_types.pop(idx, "text")
            if buf:
                tail = buf.flush()
                if tail:
                    rehyd = await rehydrator.rehydrate(tail, project=project)
                    if btype == "tool_use":
                        flush_delta = {"type": "input_json_delta", "partial_json": rehyd}
                    else:
                        flush_delta = {"type": "text_delta", "text": rehyd}
                    flush_event = {"index": idx, "delta": flush_delta}
                    yield _format_sse("content_block_delta", flush_event)
            yield _format_sse(event, data)
        else:
            yield _format_sse(event, data)

    async for raw_chunk in upstream:
        line_buf += raw_chunk
        while b"\n\n" in line_buf:
            block, line_buf = line_buf.split(b"\n\n", 1)
            for event, data in _parse_sse(block + b"\n\n"):
                async for chunk in _handle_event(event, data):
                    yield chunk

    if line_buf.strip():
        for event, data in _parse_sse(line_buf):
            yield _format_sse(event, data)
