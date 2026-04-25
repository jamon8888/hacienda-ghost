"""Tests for the SSE chunk parser used by the forward-proxy SSE rehydrator."""
from __future__ import annotations

from piighost.proxy.forward.sse import (
    SSEEvent,
    parse_sse_chunks,
    rebuild_sse_chunk,
)


def test_parse_single_event():
    raw = b"event: message_start\ndata: {\"type\":\"message_start\"}\n\n"

    events = list(parse_sse_chunks(raw))

    assert len(events) == 1
    assert events[0].event == "message_start"
    assert events[0].data == '{"type":"message_start"}'


def test_parse_multiple_events():
    raw = (
        b"event: message_start\ndata: {\"type\":\"message_start\"}\n\n"
        b"event: content_block_delta\ndata: {\"type\":\"text_delta\",\"text\":\"hi\"}\n\n"
    )

    events = list(parse_sse_chunks(raw))

    assert len(events) == 2
    assert events[1].event == "content_block_delta"


def test_parse_handles_partial_chunk_at_end():
    raw = b"event: message_start\ndata: {\"type\":\"message_start\"}\n\nevent: partial\ndata: {"

    events = list(parse_sse_chunks(raw))

    assert len(events) == 1  # incomplete trailing event dropped


def test_rebuild_round_trip():
    event = SSEEvent(event="content_block_delta", data='{"type":"text_delta","text":"hi"}')

    chunk = rebuild_sse_chunk(event)

    assert chunk == b"event: content_block_delta\ndata: {\"type\":\"text_delta\",\"text\":\"hi\"}\n\n"


def test_parse_event_without_event_field_uses_message_default():
    """Per W3C SSE: if no `event:` line, the event type is `message`."""
    raw = b"data: {\"x\": 1}\n\n"

    events = list(parse_sse_chunks(raw))

    assert len(events) == 1
    assert events[0].event == "message"
    assert events[0].data == '{"x": 1}'
