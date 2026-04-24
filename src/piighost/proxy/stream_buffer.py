"""Tail-buffered stream rewriter for split placeholder tokens.

Placeholders like `<PERSON:a3f8b2c1>` can be split across SSE deltas.
This buffer holds up to `max_tail` trailing bytes so partial placeholders
survive until their closing `>` arrives.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Match a complete placeholder. Must match piighost.placeholder format.
# Example: <PERSON:a3f8b2c1>
_PLACEHOLDER = re.compile(r"<[A-Z_]+:[a-zA-Z0-9_-]+>")

# A trailing partial is: "<" optionally followed by a partial of <LABEL:HEX
# We recognize a trailing partial by matching from "<" to end-of-string
# with the tail containing no ">".
_PARTIAL_START = re.compile(r"<[A-Z_]*(?::[a-zA-Z0-9_-]*)?$")


@dataclass
class StreamBuffer:
    """Accumulates deltas; emits text with complete placeholders preserved,
    retaining only trailing partial placeholder fragments.
    """

    max_tail: int = 64
    _held: str = field(default="")

    def feed(self, chunk: str) -> str:
        """Append `chunk`; return the safe-to-emit prefix."""
        combined = self._held + chunk
        if not combined:
            return ""

        # Find any trailing partial placeholder starting with "<" that
        # hasn't closed yet.
        m = _PARTIAL_START.search(combined)
        if m is None:
            # No trailing partial — emit everything.
            self._held = ""
            return combined

        boundary = m.start()
        emit = combined[:boundary]
        tail = combined[boundary:]

        # If tail exceeds max_tail, force-flush it (overflow guard).
        if len(tail) > self.max_tail:
            self._held = ""
            return combined

        self._held = tail
        return emit

    def flush(self) -> str:
        """Return any held partial bytes and clear state."""
        out = self._held
        self._held = ""
        return out
