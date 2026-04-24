from __future__ import annotations

import json
from typing import AsyncIterator

import pytest

from piighost.proxy.rewrite_response import rewrite_sse_stream


class FakeRehydrator:
    """Replaces <PERSON:1> with 'Jean Dupont'."""

    async def rehydrate(self, text: str, *, project: str) -> str:
        return text.replace("<PERSON:1>", "Jean Dupont")


async def _stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for c in chunks:
        yield c


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


@pytest.mark.asyncio
async def test_rehydrate_text_delta() -> None:
    upstream = [
        _sse("message_start", {"type": "message_start"}),
        _sse("content_block_start", {"index": 0, "content_block": {"type": "text"}}),
        _sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Hello <PERSON:1>!"}}),
        _sse("content_block_stop", {"index": 0}),
        _sse("message_stop", {}),
    ]
    result = b""
    async for chunk in rewrite_sse_stream(_stream(upstream), FakeRehydrator(), project="p1"):
        result += chunk
    assert b"Hello Jean Dupont!" in result
    assert b"<PERSON:1>" not in result


@pytest.mark.asyncio
async def test_rehydrate_placeholder_split_across_deltas() -> None:
    upstream = [
        _sse("content_block_start", {"index": 0, "content_block": {"type": "text"}}),
        _sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "hi <PERSO"}}),
        _sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "N:1> bye"}}),
        _sse("content_block_stop", {"index": 0}),
    ]
    result = b""
    async for chunk in rewrite_sse_stream(_stream(upstream), FakeRehydrator(), project="p1"):
        result += chunk
    assert b"Jean Dupont" in result
    assert b"<PERSON" not in result


@pytest.mark.asyncio
async def test_non_text_events_pass_through() -> None:
    upstream = [
        _sse("message_start", {"type": "message_start", "message": {"id": "msg_1"}}),
        _sse("message_stop", {}),
    ]
    result = b""
    async for chunk in rewrite_sse_stream(_stream(upstream), FakeRehydrator(), project="p1"):
        result += chunk
    assert b"msg_1" in result


@pytest.mark.asyncio
async def test_rehydrate_input_json_delta() -> None:
    upstream = [
        _sse(
            "content_block_delta",
            {"index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"path":"<PERSON:1>"}'}},
        ),
    ]
    result = b""
    async for chunk in rewrite_sse_stream(_stream(upstream), FakeRehydrator(), project="p1"):
        result += chunk
    assert b"Jean Dupont" in result
    assert b"<PERSON:1>" not in result
