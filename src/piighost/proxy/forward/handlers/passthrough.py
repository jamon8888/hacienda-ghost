"""No-op handler for endpoints that carry no PII (e.g., /v1/models)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from piighost.proxy.forward.handlers.base import Handler

if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow


class PassthroughHandler(Handler):
    """Lets the request and response flow through mitmproxy unchanged."""

    async def handle_request(self, flow: "HTTPFlow") -> None:
        return None

    async def handle_response(self, flow: "HTTPFlow") -> None:
        return None
