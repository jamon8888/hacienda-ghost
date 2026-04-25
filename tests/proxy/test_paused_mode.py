"""Tests for the paused-mode flag.

When ``<vault>/paused`` exists, the proxy must skip anonymization on
/v1/messages and forward the request body untouched. This is the "off"
state of ``piighost on/off`` — the daemon stays running so strict-mode
hosts redirects keep working, but PII rewriting is disabled.
"""
from __future__ import annotations

from pathlib import Path

import httpx
from starlette.testclient import TestClient

from piighost.proxy.server import build_app


class _RewriteService:
    """Stub service that mangles input deterministically.

    If the proxy correctly bypasses the service in paused mode, the upstream
    body should contain the *original* text — never the rewritten one.
    """

    async def anonymize(self, text: str, *, project: str) -> tuple[str, dict]:
        return text.replace("Jean Dupont", "<PERSON:1>"), {
            "entities": [{"label": "PERSON", "count": 1}]
        }

    async def rehydrate(self, text: str, *, project: str) -> str:
        return text.replace("<PERSON:1>", "Jean Dupont")

    async def active_project(self) -> str:
        return "p1"


def _mock_transport(captured: list[bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(
            200,
            content=b"event: message_stop\ndata: {}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    return httpx.MockTransport(handler)


def test_paused_flag_bypasses_anonymization(stub_vault: Path) -> None:
    """With <vault>/paused present, raw text is forwarded unchanged."""
    (stub_vault / "paused").touch()

    captured: list[bytes] = []
    app = build_app(
        service=_RewriteService(),
        vault_dir=stub_vault,
        upstream_transport=_mock_transport(captured),
    )

    payload = {
        "model": "claude-opus-4-7",
        "messages": [{"role": "user", "content": "Hello Jean Dupont"}],
    }
    with TestClient(app) as client:
        r = client.post("/v1/messages", json=payload,
                        headers={"authorization": "Bearer sk-test"})
        assert r.status_code == 200

    assert captured, "upstream was never called"
    body = captured[0].decode()
    assert "Jean Dupont" in body, "paused mode must forward raw text"
    assert "<PERSON:1>" not in body, "paused mode must not rewrite"


def test_no_paused_flag_anonymizes_as_normal(stub_vault: Path) -> None:
    """Without the flag, anonymization runs (existing behaviour)."""
    assert not (stub_vault / "paused").exists()

    captured: list[bytes] = []
    app = build_app(
        service=_RewriteService(),
        vault_dir=stub_vault,
        upstream_transport=_mock_transport(captured),
    )

    payload = {
        "model": "claude-opus-4-7",
        "messages": [{"role": "user", "content": "Hello Jean Dupont"}],
    }
    with TestClient(app) as client:
        r = client.post("/v1/messages", json=payload,
                        headers={"authorization": "Bearer sk-test"})
        assert r.status_code == 200

    body = captured[0].decode()
    assert "Jean Dupont" not in body
    assert "<PERSON:1>" in body


def test_paused_flag_toggles_at_runtime(stub_vault: Path) -> None:
    """Creating/removing the flag flips behaviour without restarting the app."""
    captured: list[bytes] = []
    app = build_app(
        service=_RewriteService(),
        vault_dir=stub_vault,
        upstream_transport=_mock_transport(captured),
    )
    payload = {
        "model": "claude-opus-4-7",
        "messages": [{"role": "user", "content": "Hello Jean Dupont"}],
    }

    with TestClient(app) as client:
        # active
        client.post("/v1/messages", json=payload,
                    headers={"authorization": "Bearer sk-test"})
        # paused
        (stub_vault / "paused").touch()
        client.post("/v1/messages", json=payload,
                    headers={"authorization": "Bearer sk-test"})
        # active again
        (stub_vault / "paused").unlink()
        client.post("/v1/messages", json=payload,
                    headers={"authorization": "Bearer sk-test"})

    assert len(captured) == 3
    bodies = [b.decode() for b in captured]
    assert "<PERSON:1>" in bodies[0]
    assert "Jean Dupont" in bodies[1] and "<PERSON:1>" not in bodies[1]
    assert "<PERSON:1>" in bodies[2]


def test_messages_works_without_x_piighost_token_header(stub_vault: Path) -> None:
    """Regression: Claude Code does not send x-piighost-token. The proxy must
    accept its requests anyway, even when build_app was given a non-empty token.
    """
    captured: list[bytes] = []
    app = build_app(
        service=_RewriteService(),
        vault_dir=stub_vault,
        upstream_transport=_mock_transport(captured),
        token="some-handshake-token-that-clients-never-see",
    )

    with TestClient(app) as client:
        r = client.post(
            "/v1/messages",
            json={"model": "x", "messages": [{"role": "user", "content": "hi"}]},
            headers={"authorization": "Bearer sk-test"},
            # NOTE: deliberately no x-piighost-token header
        )

    assert r.status_code == 200, (
        f"got {r.status_code}: {r.content!r}. Token gate must not block "
        f"clients that have no way to learn the handshake token."
    )
