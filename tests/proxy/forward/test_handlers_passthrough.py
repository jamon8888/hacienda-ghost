"""Tests for the no-op passthrough handler used for /v1/models etc."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from piighost.proxy.forward.handlers.passthrough import PassthroughHandler


@pytest.mark.asyncio
async def test_passthrough_does_not_set_response_on_request():
    handler = PassthroughHandler()
    flow = MagicMock()
    flow.response = None

    await handler.handle_request(flow)

    assert flow.response is None  # request was forwarded untouched


@pytest.mark.asyncio
async def test_passthrough_does_not_modify_response():
    handler = PassthroughHandler()
    flow = MagicMock()
    flow.response = MagicMock()
    pre = flow.response

    await handler.handle_response(flow)

    assert flow.response is pre
