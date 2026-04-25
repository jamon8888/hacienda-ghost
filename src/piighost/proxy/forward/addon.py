"""mitmproxy addon: routes Anthropic-bound flows through piighost handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from piighost.proxy.forward.dispatch import Dispatcher

if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow

DEFAULT_ANTHROPIC_HOSTS: frozenset[str] = frozenset({"api.anthropic.com"})


class PiighostAddon:
    """mitmproxy addon class. Hooks `request` and `response` events.

    Only flows targeting hosts in `anthropic_hosts` are inspected;
    everything else passes through untouched (raw tunneling for
    non-Anthropic CONNECT happens at the mitmproxy mode/options level).
    """

    def __init__(
        self,
        *,
        dispatcher: Dispatcher,
        anthropic_hosts: Iterable[str] = DEFAULT_ANTHROPIC_HOSTS,
    ) -> None:
        self._dispatcher = dispatcher
        self._hosts = frozenset(anthropic_hosts)

    async def request(self, flow: "HTTPFlow") -> None:
        if not self._is_anthropic(flow):
            return
        handler = self._dispatcher.dispatch(
            method=flow.request.method, path=flow.request.path
        )
        await handler.handle_request(flow)

    async def response(self, flow: "HTTPFlow") -> None:
        if flow.response is None or not self._is_anthropic(flow):
            return
        handler = self._dispatcher.dispatch(
            method=flow.request.method, path=flow.request.path
        )
        await handler.handle_response(flow)

    def _is_anthropic(self, flow: "HTTPFlow") -> bool:
        host = getattr(flow.request, "pretty_host", None) or flow.request.host
        return host in self._hosts
