"""Abstract base class for endpoint handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow


class Handler(ABC):
    """One handler per (method, path) entry in the coverage matrix.

    Implementations mutate `flow.request` in `handle_request` (e.g.,
    rewrite the JSON body) and `flow.response` in `handle_response`
    (e.g., rehydrate SSE placeholders).
    """

    @abstractmethod
    async def handle_request(self, flow: "HTTPFlow") -> None: ...

    @abstractmethod
    async def handle_response(self, flow: "HTTPFlow") -> None: ...
