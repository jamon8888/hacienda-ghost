"""Tests for the fail-closed unknown-endpoint handler."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from piighost.proxy.forward.handlers.unknown import UnknownEndpointHandler


def _make_flow(method: str = "POST", path: str = "/v1/wat") -> MagicMock:
    flow = MagicMock()
    flow.request.method = method
    flow.request.path = path
    flow.request.host = "api.anthropic.com"
    flow.response = None
    return flow


@pytest.mark.asyncio
async def test_unknown_endpoint_returns_403_via_response():
    handler = UnknownEndpointHandler(audit_writer=None)
    flow = _make_flow()

    await handler.handle_request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 403


@pytest.mark.asyncio
async def test_unknown_endpoint_writes_audit_record():
    audit = MagicMock()
    handler = UnknownEndpointHandler(audit_writer=audit)
    flow = _make_flow(method="GET", path="/v1/future_endpoint")

    await handler.handle_request(flow)

    assert audit.write.called
    record = audit.write.call_args[0][0]
    assert record.status == "blocked_unknown_endpoint"
    assert "/v1/future_endpoint" in str(record.host)


@pytest.mark.asyncio
async def test_unknown_endpoint_response_body_is_json():
    handler = UnknownEndpointHandler(audit_writer=None)
    flow = _make_flow()

    await handler.handle_request(flow)

    assert flow.response is not None
    body = json.loads(flow.response.content)  # type: ignore[arg-type]
    assert body["error"].startswith("piighost: endpoint not in coverage matrix")


@pytest.mark.asyncio
async def test_unknown_endpoint_handle_response_is_noop():
    handler = UnknownEndpointHandler(audit_writer=None)
    flow = _make_flow()
    flow.response = MagicMock()
    pre = flow.response

    await handler.handle_response(flow)

    assert flow.response is pre  # untouched
