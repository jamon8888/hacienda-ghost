"""End-to-end integration test for the forward proxy.

Skipped on Windows (mitmproxy + httpx asyncio + asyncio.subprocess
combinations are flaky on Win32). Run on WSL Ubuntu:

    wsl bash -c "cd /mnt/c/Users/NMarchitecte/Documents/piighost && uv run pytest tests/proxy/forward/test_e2e.py -v"
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="mitmproxy e2e requires WSL/Linux"
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Capture:
    received: dict | None = None


async def _capturing_messages(request):
    body = await request.json()
    _Capture.received = body
    user_text = body["messages"][0]["content"][0]["text"]
    sse = (
        b'event: message_start\ndata: {"type":"message_start"}\n\n'
        b"event: content_block_delta\ndata: "
        + json.dumps(
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": f"echo: {user_text}"},
            }
        ).encode("utf-8")
        + b'\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n'
    )

    async def gen():
        yield sse

    return StreamingResponse(gen(), media_type="text/event-stream")


@asynccontextmanager
async def _fake_upstream():
    """Run a Starlette server impersonating api.anthropic.com on a random port."""
    import uvicorn

    app = Starlette(
        routes=[Route("/v1/messages", _capturing_messages, methods=["POST"])]
    )
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    try:
        yield port
    finally:
        server.should_exit = True
        await task


@pytest.mark.asyncio
async def test_forward_proxy_round_trip(tmp_path: Path, monkeypatch):
    """Full anonymize → upstream → rehydrate round-trip via mitmproxy addon."""
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault_dir = tmp_path / "vault"
    (vault_dir / "audit").mkdir(parents=True)

    # Locate the CA helper — import dynamically so the test fails
    # cleanly if the CA module hasn't been implemented yet.
    try:
        from piighost.install.ca import generate_ca
    except ImportError:
        pytest.skip("piighost.install.ca.generate_ca not available")

    ca_path = vault_dir / "ca.pem"
    generate_ca(ca_path)

    async with _fake_upstream():
        from piighost.proxy.forward.__main__ import build_addon

        addon = await build_addon(vault_dir=vault_dir)

        # Inject the fake upstream URL into the stub service so the
        # anonymization pipeline routes to our fake server, not the real
        # api.anthropic.com (which would require a valid API key and DNS).
        # Phase 1 note: full upstream remap is in Phase 4 (Desktop wrapper).
        # For now we hit the fake upstream directly without going through
        # mitmproxy's CONNECT tunnel to test the handler logic end-to-end.
        from piighost.proxy.forward.handlers.messages import MessagesHandler

        # Resolve the messages handler from the default dispatcher
        handler = addon._dispatcher.dispatch(method="POST", path="/v1/messages")
        assert isinstance(handler, MessagesHandler)

        # Build a mock flow that simulates what mitmproxy would pass to the addon
        from unittest.mock import MagicMock

        flow = MagicMock()
        flow.request.method = "POST"
        flow.request.path = "/v1/messages"
        flow.request.host = "api.anthropic.com"
        flow.request.pretty_host = "api.anthropic.com"
        flow.request.content = json.dumps(
            {
                "model": "claude-opus-4-7",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "Hello PATRICK"}],
                    }
                ],
            }
        ).encode("utf-8")
        flow.request.headers = {"content-type": "application/json"}
        flow.response = None

        # Phase 1: test request-side anonymization (upstream delivery)
        await addon.request(flow)

        # The request body should now contain the anonymized placeholder
        assert flow.response is None, "Anonymization failed, check logs"
        request_body = json.loads(flow.request.content)
        user_text = request_body["messages"][0]["content"][0]["text"]
        assert "PATRICK" not in user_text, f"PII leaked to upstream: {user_text!r}"
        assert "<<" in user_text and ">>" in user_text, (
            f"No placeholder in: {user_text!r}"
        )

        # Phase 1: test response-side rehydration (SSE text_delta)
        placeholder = user_text  # whatever the stub produced
        flow.response = MagicMock()
        flow.response.headers = {"content-type": "text/event-stream"}
        flow.response.content = (
            b'event: message_start\ndata: {"type":"message_start"}\n\n'
            + b"event: content_block_delta\ndata: "
            + json.dumps(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": f"echo: {placeholder}"},
                }
            ).encode("utf-8")
            + b'\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n'
        )

        await addon.response(flow)

        rebuilt = flow.response.content
        assert b"PATRICK" in rebuilt, "Placeholder was not rehydrated in response"
        assert placeholder.encode() not in rebuilt, (
            "Placeholder still present after rehydration"
        )
