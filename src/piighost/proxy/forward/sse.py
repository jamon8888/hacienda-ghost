"""Server-Sent Events chunk parser/rebuilder for streaming rehydration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class SSEEvent:
    event: str  # defaults to "message" per W3C SSE spec
    data: str


def parse_sse_chunks(raw: bytes) -> Iterator[SSEEvent]:
    """Parse complete SSE events from a raw byte buffer.

    Incomplete trailing events (no terminating blank line) are dropped.
    Caller is responsible for buffering across read boundaries.
    """
    text = raw.decode("utf-8", errors="replace")
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        # Reject incomplete blocks that lack the double-newline terminator.
        # We detect this by confirming the original text contains the
        # block followed by "\n\n":
        if (block + "\n\n") not in text:
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip())
        yield SSEEvent(event=event_name, data="\n".join(data_lines))


def rebuild_sse_chunk(event: SSEEvent) -> bytes:
    """Encode an SSEEvent back to wire bytes including the terminator."""
    lines = []
    if event.event != "message":
        lines.append(f"event: {event.event}")
    lines.append(f"data: {event.data}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")
