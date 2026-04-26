"""Streaming-safe rehydrator — guarantees no partial <LABEL:hash> ever leaves."""

from __future__ import annotations

import re

from piighost.service.core import PIIGhostService


# Matches an in-progress placeholder token at the end of the buffer so we
# can hold it back until the full token arrives. Tokens are wrapped in
# ``<<LABEL:value>>`` (Hash/Counter factories) — we also tolerate a single
# leading ``<`` because chunk boundaries may split the wrapper itself.
_OPEN_TOKEN_RE = re.compile(r"<<?[A-Z_]*:?[0-9a-zA-Z]*>?$")


class StreamingRehydrator:
    """Rolling-buffer rehydrator for incremental LLM output.

    The LLM may split a token like ``<PERSON:abc12345>`` across multiple
    chunks. This class buffers trailing text that looks like an
    in-progress token and only emits rehydrated text up to the last safe
    cut point.
    """

    def __init__(self, svc: PIIGhostService, project: str) -> None:
        self._svc = svc
        self._project = project
        self._buffer = ""

    async def feed(self, chunk: str) -> str:
        """Append ``chunk`` to the buffer, emit the safe prefix rehydrated."""
        self._buffer += chunk
        match = _OPEN_TOKEN_RE.search(self._buffer)
        cut = match.start() if match else len(self._buffer)
        to_emit, self._buffer = self._buffer[:cut], self._buffer[cut:]
        if not to_emit:
            return ""
        result = await self._svc.rehydrate(
            to_emit, project=self._project, strict=False
        )
        return result.text

    async def finalize(self) -> str:
        """Flush any remaining buffered text after the stream ends."""
        if not self._buffer:
            return ""
        result = await self._svc.rehydrate(
            self._buffer, project=self._project, strict=False
        )
        self._buffer = ""
        return result.text
