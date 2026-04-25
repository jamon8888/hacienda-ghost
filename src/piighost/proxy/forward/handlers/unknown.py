"""Fail-closed handler for endpoints not in the coverage matrix."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from mitmproxy.http import Response

from piighost.proxy.audit import AuditRecord, AuditWriter
from piighost.proxy.forward.handlers.base import Handler

if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow

_BLOCK_BODY = {
    "error": "piighost: endpoint not in coverage matrix; update piighost or contact support",
    "type": "piighost_block",
}


class UnknownEndpointHandler(Handler):
    """Returns HTTP 403 for any request that did not match the coverage matrix.

    This is the fail-closed default: future Anthropic endpoints will be
    rejected until explicitly added to the coverage matrix.
    """

    def __init__(self, audit_writer: Optional[AuditWriter]) -> None:
        self._audit = audit_writer

    async def handle_request(self, flow: "HTTPFlow") -> None:
        flow.response = Response.make(
            403,
            json.dumps(_BLOCK_BODY).encode("utf-8"),
            {"content-type": "application/json"},
        )
        if self._audit is not None:
            self._audit.write(
                AuditRecord(
                    ts=datetime.now(timezone.utc),
                    request_id="",
                    project="",
                    host=f"{flow.request.method} {flow.request.path}",
                    model="",
                    entities_detected=[],
                    placeholders_emitted=0,
                    request_bytes_in=0,
                    request_bytes_out=0,
                    stream_duration_ms=0,
                    rehydration_errors=0,
                    status="blocked_unknown_endpoint",
                )
            )

    async def handle_response(self, flow: "HTTPFlow") -> None:
        return None
