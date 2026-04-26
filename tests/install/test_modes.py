from __future__ import annotations

from pathlib import Path

import pytest

from piighost.install.modes import (
    run_light_mode_proxy,
    run_strict_mode_proxy,
    run_mcp_only,
)
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _plan(tmp_path, mode, **overrides):
    base = dict(
        mode=mode,
        vault_dir=tmp_path / "vault",
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=frozenset(),
        install_user_service=mode is not Mode.MCP_ONLY,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    base.update(overrides)
    return InstallPlan(**base)


def test_run_light_mode_proxy_invokes_legacy_runner(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(
        "piighost.install._run_light_mode",
        lambda: called.setdefault("light", True),
    )
    plan = _plan(tmp_path, Mode.FULL)
    run_light_mode_proxy(plan)
    assert called.get("light") is True


def test_run_strict_mode_proxy_invokes_legacy_runner(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(
        "piighost.install._run_strict_mode",
        lambda: called.setdefault("strict", True),
    )
    plan = _plan(tmp_path, Mode.STRICT)
    run_strict_mode_proxy(plan)
    assert called.get("strict") is True


def test_run_mcp_only_is_noop(tmp_path):
    plan = _plan(tmp_path, Mode.MCP_ONLY, install_user_service=False)
    run_mcp_only(plan)  # must not raise
