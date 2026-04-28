"""PisteClient — sync httpx wrapper for OpenLégi MCP endpoint."""
from __future__ import annotations

import json

import httpx
import pytest

from piighost.legal.piste_client import PisteClient


def _sse(payload: dict) -> str:
    """OpenLégi returns SSE — encode a dict as one event."""
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def test_call_tool_happy_path(httpx_mock):
    """call_tool dispatches a tools/call JSON-RPC and parses SSE response."""
    httpx_mock.add_response(
        url="https://mcp.openlegi.fr/legifrance",
        method="POST",
        text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": [{"title": "Art. 1240"}]}}),
        headers={"Content-Type": "text/event-stream"},
    )
    with PisteClient(token="fake-token") as c:
        result = c.call_tool("rechercher_code", {"code_name": "Code civil", "search": "1240"})
    assert result == {"hits": [{"title": "Art. 1240"}]}


def test_authorization_header_set(httpx_mock):
    httpx_mock.add_response(
        url="https://mcp.openlegi.fr/legifrance",
        text=_sse({"jsonrpc": "2.0", "id": 1, "result": {}}),
    )
    with PisteClient(token="abc-123") as c:
        c.call_tool("rechercher_code", {})
    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer abc-123"


def test_429_retries_with_backoff(httpx_mock, monkeypatch):
    """On HTTP 429 we retry up to 3 times with backoff."""
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    httpx_mock.add_response(status_code=429)
    httpx_mock.add_response(status_code=429)
    httpx_mock.add_response(text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}))

    with PisteClient(token="x") as c:
        result = c.call_tool("rechercher_code", {})
    assert result == {"ok": True}
    assert len(sleeps) == 2  # two retries with sleeps


def test_429_exhausts_retries(httpx_mock):
    for _ in range(4):
        httpx_mock.add_response(status_code=429)

    with PisteClient(token="x", max_retries=3) as c:
        with pytest.raises(httpx.HTTPStatusError):
            c.call_tool("rechercher_code", {})


def test_401_does_not_retry(httpx_mock):
    httpx_mock.add_response(status_code=401)
    with PisteClient(token="bad") as c:
        with pytest.raises(httpx.HTTPStatusError):
            c.call_tool("rechercher_code", {})
    # Only one request — auth errors are not retried
    assert len(httpx_mock.get_requests()) == 1


def test_malformed_sse_raises_parse_error(httpx_mock):
    httpx_mock.add_response(text="garbage with no SSE structure")
    with PisteClient(token="x") as c:
        with pytest.raises(ValueError, match="(parse|SSE|JSON)"):
            c.call_tool("rechercher_code", {})


def test_custom_base_url(httpx_mock):
    httpx_mock.add_response(
        url="https://my-self-hosted.example.com/legifrance",
        text=_sse({"jsonrpc": "2.0", "id": 1, "result": {}}),
    )
    with PisteClient(
        token="x",
        base_url="https://my-self-hosted.example.com",
    ) as c:
        c.call_tool("rechercher_code", {})


def test_list_tools_returns_metadata(httpx_mock):
    httpx_mock.add_response(text=_sse({
        "jsonrpc": "2.0", "id": 1,
        "result": {"tools": [{"name": "rechercher_code", "description": "…"}]},
    }))
    with PisteClient(token="x") as c:
        tools = c.list_tools()
    assert tools == [{"name": "rechercher_code", "description": "…"}]


def test_request_error_retries_then_succeeds(httpx_mock, monkeypatch):
    """Transient connection failures retry up to max_retries."""
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    # First two attempts: ConnectError; third: success
    httpx_mock.add_exception(httpx.ConnectError("name resolution failed"))
    httpx_mock.add_exception(httpx.ConnectError("name resolution failed"))
    httpx_mock.add_response(text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}))

    with PisteClient(token="x", max_retries=3) as c:
        result = c.call_tool("rechercher_code", {})
    assert result == {"ok": True}
    assert len(sleeps) == 2  # two retries with backoff


def test_request_error_exhausts_retries_then_raises(httpx_mock, monkeypatch):
    """After exhausting retries on RequestError, the exception bubbles."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Initial attempt + max_retries (3) = 4 connection failures
    for _ in range(4):
        httpx_mock.add_exception(httpx.ConnectError("DNS down"))

    with PisteClient(token="x", max_retries=3) as c:
        with pytest.raises(httpx.RequestError):
            c.call_tool("rechercher_code", {})
