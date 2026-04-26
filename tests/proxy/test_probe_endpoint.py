"""Tests for the /piighost-probe unauthenticated endpoint."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient


def _build_test_app(tmp_path: Path) -> "TestClient":
    from piighost.proxy.server import build_app

    service = MagicMock()
    service.active_project = AsyncMock(return_value="test-project")
    service.anonymize = AsyncMock(return_value=("text", {}))
    service.rehydrate = AsyncMock(return_value="text")

    app = build_app(service=service, vault_dir=tmp_path, token="")
    return TestClient(app, raise_server_exceptions=True)


def test_probe_returns_intercepted_true(tmp_path: Path) -> None:
    client = _build_test_app(tmp_path)
    r = client.get("/piighost-probe")
    assert r.status_code == 200
    data = r.json()
    assert data["intercepted"] is True
    assert data["proxy"] == "piighost"


def test_probe_requires_no_token(tmp_path: Path) -> None:
    from piighost.proxy.server import build_app

    service = MagicMock()
    service.active_project = AsyncMock(return_value="test-project")
    app = build_app(service=service, vault_dir=tmp_path, token="secret-token")
    client = TestClient(app)

    # No x-piighost-token header — probe must still succeed
    r = client.get("/piighost-probe")
    assert r.status_code == 200
    assert r.json()["intercepted"] is True


def test_probe_is_get_only(tmp_path: Path) -> None:
    """POST to /piighost-probe must NOT return the intercepted=True signal.

    The probe is GET-only by intent. After the catch-all passthrough route
    was added, a POST falls through to the upstream forwarder rather than
    returning 405 directly — but the user-visible contract is the same:
    a non-GET request never produces the probe success payload.
    """
    client = _build_test_app(tmp_path)
    r = client.post("/piighost-probe")
    assert r.status_code != 200, "POST must not return the probe success payload"
    # The body may be empty / non-JSON if it routes through passthrough.
    # The contract is "POST does not produce the probe success payload",
    # which the status_code != 200 already guarantees.
