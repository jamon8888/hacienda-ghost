"""Tests for the mitmproxy addon dispatch glue."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from piighost.proxy.forward.addon import PiighostAddon
from piighost.proxy.forward.dispatch import Dispatcher
from piighost.proxy.forward.handlers.passthrough import PassthroughHandler


def _flow(host: str = "api.anthropic.com", method: str = "GET", path: str = "/v1/models"):
    flow = MagicMock()
    flow.request.host = host
    flow.request.pretty_host = host
    flow.request.method = method
    flow.request.path = path
    flow.response = None
    return flow


@pytest.mark.asyncio
async def test_request_hook_dispatches_to_handler():
    handler = PassthroughHandler()
    handler.handle_request = AsyncMock()  # type: ignore[method-assign]
    dispatcher = Dispatcher(
        matrix={("GET", "/v1/models"): handler},
        default=PassthroughHandler(),
    )
    addon = PiighostAddon(dispatcher=dispatcher, anthropic_hosts={"api.anthropic.com"})
    flow = _flow()

    await addon.request(flow)

    handler.handle_request.assert_awaited_once_with(flow)


@pytest.mark.asyncio
async def test_request_hook_skips_non_anthropic_hosts():
    handler = PassthroughHandler()
    handler.handle_request = AsyncMock()  # type: ignore[method-assign]
    dispatcher = Dispatcher(
        matrix={("GET", "/v1/models"): handler},
        default=PassthroughHandler(),
    )
    addon = PiighostAddon(dispatcher=dispatcher, anthropic_hosts={"api.anthropic.com"})
    flow = _flow(host="github.com", path="/v1/models")

    await addon.request(flow)

    handler.handle_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_response_hook_dispatches_to_same_handler():
    handler = PassthroughHandler()
    handler.handle_response = AsyncMock()  # type: ignore[method-assign]
    dispatcher = Dispatcher(
        matrix={("GET", "/v1/models"): handler},
        default=PassthroughHandler(),
    )
    addon = PiighostAddon(dispatcher=dispatcher, anthropic_hosts={"api.anthropic.com"})
    flow = _flow()
    flow.response = MagicMock()

    await addon.response(flow)

    handler.handle_response.assert_awaited_once_with(flow)
