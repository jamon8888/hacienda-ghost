from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from piighost.proxy.server import build_app


# Deny list: raw PII strings that must NEVER appear in upstream traffic.
_RAW_PII = [
    r"Jean Dupont",
    r"Marie Curie",
    r"12 rue de Rivoli",
    r"0612345678",
    r"FR76 1234 5678 9012 3456 7890 123",
]


class LeakDetectingService:
    """Stub service that anonymizes the known raw PII strings."""

    def __init__(self) -> None:
        self._map = {
            "Jean Dupont": "<PERSON:1>",
            "Marie Curie": "<PERSON:2>",
            "12 rue de Rivoli": "<ADDRESS:1>",
            "0612345678": "<PHONE:1>",
            "FR76 1234 5678 9012 3456 7890 123": "<IBAN:1>",
        }

    async def anonymize(self, text: str, *, project: str) -> tuple[str, dict]:
        out = text
        entities = []
        for raw, ph in self._map.items():
            if raw in out:
                out = out.replace(raw, ph)
                entities.append({"label": ph.split(":")[0].strip("<"), "count": 1})
        return out, {"entities": entities}

    async def rehydrate(self, text: str, *, project: str) -> str:
        out = text
        for raw, ph in self._map.items():
            out = out.replace(ph, raw)
        return out

    async def active_project(self) -> str:
        return "leak-test"


def test_no_raw_pii_reaches_upstream(tmp_path: Path) -> None:
    """The core contract: raw PII never leaves the proxy to upstream."""
    captured_bodies: list[bytes] = []

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(request.content)
        return httpx.Response(
            200,
            content=b"event: message_stop\ndata: {}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    vault = tmp_path / ".piighost"
    vault.mkdir()

    app = build_app(
        service=LeakDetectingService(),
        vault_dir=vault,
        upstream_transport=httpx.MockTransport(capturing_handler),
    )

    payload = {
        "model": "claude-opus-4-7",
        "system": "Jean Dupont is our client",
        "messages": [
            {
                "role": "user",
                "content": "Marie Curie lives at 12 rue de Rivoli, tel 0612345678.",
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"path": "/clients/Jean Dupont/notes.txt"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": "IBAN: FR76 1234 5678 9012 3456 7890 123",
                    }
                ],
            },
        ],
    }

    with TestClient(app) as client:
        r = client.post(
            "/v1/messages",
            json=payload,
            headers={"authorization": "Bearer sk-test"},
        )
        assert r.status_code == 200

    assert captured_bodies, "upstream was never called"
    all_upstream = b"".join(captured_bodies).decode("utf-8", errors="replace")

    for pattern in _RAW_PII:
        assert not re.search(pattern, all_upstream), (
            f"Raw PII leak to upstream: {pattern!r} found in: {all_upstream[:500]}"
        )
