"""Smoke test: forward-proxy main builds an addon without crashing.

Does NOT bind to a real port — that's covered by the e2e test in
test_e2e.py. This test only validates wiring: anonymization service
construction, dispatcher build, addon instantiation, and CA path
resolution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from piighost.proxy.forward.__main__ import build_addon


@pytest.mark.asyncio
async def test_build_addon_returns_addon(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    addon = await build_addon(vault_dir=vault_dir)

    assert addon is not None
    assert hasattr(addon, "request")
    assert hasattr(addon, "response")
