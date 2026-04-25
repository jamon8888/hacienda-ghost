"""Tests for MessagesHandler text and system field anonymization."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from piighost.proxy.forward.handlers.messages import MessagesHandler


def _make_request_flow(body: dict) -> MagicMock:
    flow = MagicMock()
    flow.request.method = "POST"
    flow.request.path = "/v1/messages"
    flow.request.host = "api.anthropic.com"
    flow.request.content = json.dumps(body).encode("utf-8")
    flow.request.headers = {"content-type": "application/json"}
    flow.response = None
    return flow


@pytest.mark.asyncio
async def test_anonymizes_text_content_block(stub_service):
    handler = MessagesHandler(service=stub_service)
    flow = _make_request_flow({
        "model": "claude-opus-4-7",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello PATRICK"}],
            }
        ],
    })

    await handler.handle_request(flow)

    body = json.loads(flow.request.content)
    assert body["messages"][0]["content"][0]["text"] == "Hello <<PERSON_1>>"


@pytest.mark.asyncio
async def test_anonymizes_string_content_shorthand(stub_service):
    handler = MessagesHandler(service=stub_service)
    flow = _make_request_flow({
        "model": "claude-opus-4-7",
        "messages": [{"role": "user", "content": "Hello PATRICK"}],
    })

    await handler.handle_request(flow)

    body = json.loads(flow.request.content)
    assert body["messages"][0]["content"] == "Hello <<PERSON_1>>"


@pytest.mark.asyncio
async def test_anonymizes_system_field_string(stub_service):
    handler = MessagesHandler(service=stub_service)
    flow = _make_request_flow({
        "model": "claude-opus-4-7",
        "system": "You are PATRICK's assistant",
        "messages": [{"role": "user", "content": "hi"}],
    })

    await handler.handle_request(flow)

    body = json.loads(flow.request.content)
    assert body["system"] == "You are <<PERSON_1>>'s assistant"


@pytest.mark.asyncio
async def test_anonymizes_system_field_blocks(stub_service):
    handler = MessagesHandler(service=stub_service)
    flow = _make_request_flow({
        "model": "claude-opus-4-7",
        "system": [{"type": "text", "text": "Assist PATRICK"}],
        "messages": [{"role": "user", "content": "hi"}],
    })

    await handler.handle_request(flow)

    body = json.loads(flow.request.content)
    assert body["system"][0]["text"] == "Assist <<PERSON_1>>"


@pytest.mark.asyncio
async def test_passes_through_image_content_block_untouched(stub_service):
    handler = MessagesHandler(service=stub_service)
    flow = _make_request_flow({
        "model": "claude-opus-4-7",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "image", "source": {"type": "base64", "data": "aGVsbG8="}}],
            }
        ],
    })

    await handler.handle_request(flow)

    body = json.loads(flow.request.content)
    assert body["messages"][0]["content"][0]["type"] == "image"
    assert body["messages"][0]["content"][0]["source"]["data"] == "aGVsbG8="
    assert stub_service.calls_anonymize == []  # never called on image


@pytest.mark.asyncio
async def test_invalid_json_body_returns_400(stub_service):
    handler = MessagesHandler(service=stub_service)
    flow = MagicMock()
    flow.request.method = "POST"
    flow.request.path = "/v1/messages"
    flow.request.content = b"not json"
    flow.response = None

    await handler.handle_request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 400


@pytest.mark.asyncio
async def test_anonymization_failure_returns_503_no_upstream(stub_service):
    class Boom(type(stub_service)):
        async def anonymize(self, text, *, project):  # type: ignore[no-untyped-def]
            raise RuntimeError("GLiNER2 OOM")

    handler = MessagesHandler(service=Boom())
    flow = _make_request_flow({
        "model": "claude-opus-4-7",
        "messages": [{"role": "user", "content": "Hello PATRICK"}],
    })

    await handler.handle_request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 503


@pytest.mark.asyncio
async def test_rehydrates_text_delta_in_sse_response(stub_service):
    handler = MessagesHandler(service=stub_service)
    flow = MagicMock()
    flow.request.method = "POST"
    flow.request.path = "/v1/messages"
    flow.response = MagicMock()
    flow.response.headers = {"content-type": "text/event-stream"}
    flow.response.content = (
        b"event: message_start\ndata: {\"type\":\"message_start\"}\n\n"
        b"event: content_block_delta\ndata: {\"type\":\"content_block_delta\","
        b"\"delta\":{\"type\":\"text_delta\",\"text\":\"Hello <<PERSON_1>>\"}}\n\n"
        b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"
    )

    await handler.handle_response(flow)

    rebuilt = flow.response.content
    assert b"Hello PATRICK" in rebuilt
    assert b"<<PERSON_1>>" not in rebuilt


@pytest.mark.asyncio
async def test_rehydrate_skips_non_sse_response(stub_service):
    handler = MessagesHandler(service=stub_service)
    flow = MagicMock()
    flow.response = MagicMock()
    flow.response.headers = {"content-type": "application/json"}
    original = b'{"id":"msg_x","content":[{"type":"text","text":"Hi <<PERSON_1>>"}]}'
    flow.response.content = original

    await handler.handle_response(flow)

    # Phase 1 only rehydrates SSE; non-stream JSON rehydration is Phase 2.
    assert flow.response.content == original
