from __future__ import annotations

import os
from pathlib import Path

import pytest

from piighost.install.flags import (
    DeprecationNotice,
    FlagsResult,
    parse_flags,
)
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def test_minimal_full_flags():
    res = parse_flags(
        mode="full",
        vault_dir=None,
        embedder=None,
        mistral_api_key=None,
        clients=None,
        user_service=None,
        warmup=False,
        force=False,
        dry_run=False,
        yes=True,
        env={},
    )
    assert isinstance(res.plan, InstallPlan)
    assert res.plan.mode is Mode.FULL
    assert res.plan.embedder is Embedder.LOCAL
    assert res.plan.vault_dir == Path.home() / ".piighost" / "vault"
    assert res.plan.install_user_service is True
    assert res.deprecations == []


def test_mcp_only_defaults_user_service_off():
    res = parse_flags(
        mode="mcp-only", vault_dir=None, embedder=None,
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True, env={},
    )
    assert res.plan.mode is Mode.MCP_ONLY
    assert res.plan.install_user_service is False


def test_light_alias_emits_deprecation_and_maps_to_full():
    res = parse_flags(
        mode="light", vault_dir=None, embedder=None,
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True, env={},
    )
    assert res.plan.mode is Mode.FULL
    assert any(d.flag == "--mode=light" for d in res.deprecations)


def test_strict_warns_advanced():
    res = parse_flags(
        mode="strict", vault_dir=None, embedder=None,
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True, env={},
    )
    assert res.plan.mode is Mode.STRICT
    assert res.plan.install_user_service is True
    assert any(d.severity == "advanced" for d in res.deprecations)


def test_mistral_without_key_uses_env_var():
    res = parse_flags(
        mode="full", vault_dir=None, embedder="mistral",
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True,
        env={"MISTRAL_API_KEY": "sk-env"},
    )
    assert res.plan.mistral_api_key == "sk-env"


def test_mistral_without_key_or_env_raises():
    with pytest.raises(ValueError, match="mistral_api_key"):
        parse_flags(
            mode="full", vault_dir=None, embedder="mistral",
            mistral_api_key=None, clients=None, user_service=None,
            warmup=False, force=False, dry_run=False, yes=True, env={},
        )


def test_clients_csv_parsed():
    res = parse_flags(
        mode="full", vault_dir=None, embedder=None,
        mistral_api_key=None, clients="code,desktop",
        user_service=None, warmup=False, force=False,
        dry_run=False, yes=True, env={},
    )
    assert res.plan.clients == frozenset({Client.CLAUDE_CODE, Client.CLAUDE_DESKTOP})


def test_unknown_client_name_raises():
    with pytest.raises(ValueError, match="unknown client"):
        parse_flags(
            mode="full", vault_dir=None, embedder=None,
            mistral_api_key=None, clients="code,zoom",
            user_service=None, warmup=False, force=False,
            dry_run=False, yes=True, env={},
        )


def test_strict_with_no_user_service_raises():
    with pytest.raises(ValueError, match="strict"):
        parse_flags(
            mode="strict", vault_dir=None, embedder=None,
            mistral_api_key=None, clients=None, user_service=False,
            warmup=False, force=False, dry_run=False, yes=True, env={},
        )


def test_explicit_vault_dir_honored(tmp_path):
    res = parse_flags(
        mode="full", vault_dir=tmp_path, embedder=None,
        mistral_api_key=None, clients=None, user_service=None,
        warmup=False, force=False, dry_run=False, yes=True, env={},
    )
    assert res.plan.vault_dir == tmp_path
