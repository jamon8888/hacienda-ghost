from __future__ import annotations

from pathlib import Path

import pytest

from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _base_kwargs(**overrides):
    base = dict(
        mode=Mode.FULL,
        vault_dir=Path("/tmp/vault"),
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=frozenset({Client.CLAUDE_CODE}),
        install_user_service=True,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    base.update(overrides)
    return base


def test_default_full_plan_validates():
    plan = InstallPlan(**_base_kwargs())
    assert plan.mode is Mode.FULL
    assert plan.embedder is Embedder.LOCAL


def test_mistral_without_key_is_rejected():
    with pytest.raises(ValueError, match="mistral_api_key"):
        InstallPlan(**_base_kwargs(embedder=Embedder.MISTRAL, mistral_api_key=None))


def test_mistral_with_key_is_accepted():
    plan = InstallPlan(
        **_base_kwargs(embedder=Embedder.MISTRAL, mistral_api_key="sk-test")
    )
    assert plan.mistral_api_key == "sk-test"


def test_mcp_only_with_user_service_is_rejected():
    with pytest.raises(ValueError, match="mcp-only"):
        InstallPlan(**_base_kwargs(mode=Mode.MCP_ONLY, install_user_service=True))


def test_mcp_only_without_user_service_is_accepted():
    plan = InstallPlan(
        **_base_kwargs(mode=Mode.MCP_ONLY, install_user_service=False)
    )
    assert plan.mode is Mode.MCP_ONLY


def test_strict_without_user_service_is_rejected():
    with pytest.raises(ValueError, match="strict"):
        InstallPlan(**_base_kwargs(mode=Mode.STRICT, install_user_service=False))


def test_describe_lists_each_step():
    plan = InstallPlan(**_base_kwargs())
    out = plan.describe()
    assert "CA + leaf cert" in out
    assert "Claude Code" in out
    assert "auto-restart" in out
    assert "/tmp/vault" in out
    assert "local" in out


def test_describe_skips_proxy_lines_in_mcp_only():
    plan = InstallPlan(
        **_base_kwargs(
            mode=Mode.MCP_ONLY, install_user_service=False
        )
    )
    out = plan.describe()
    assert "CA" not in out
    assert "auto-restart" not in out


def test_describe_warns_when_embedder_is_none():
    plan = InstallPlan(**_base_kwargs(embedder=Embedder.NONE))
    out = plan.describe()
    assert "RAG indexing/query disabled" in out
