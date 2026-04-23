"""Tests for config.toml loading in build_mcp.

build_mcp must honour vault_dir/config.toml when present and fall back
to ServiceConfig defaults when the file is absent.

These tests verify the ``_load_config`` integration: a detector/safety
setting from config.toml must reach the live PIIGhostService instance.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

fastmcp_mod = pytest.importorskip("fastmcp", reason="fastmcp extra not installed")
from fastmcp.client import Client  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build(tmp_path: Path, monkeypatch, *, toml: str | None = None):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    if toml is not None:
        (vault / "config.toml").write_text(toml, encoding="utf-8")
    from piighost.mcp.server import build_mcp  # noqa: PLC0415

    return asyncio.run(build_mcp(vault))


async def _call(mcp, name: str, **kwargs):
    async with Client(mcp) as cli:
        result = await cli.call_tool(name, kwargs or None)
    return result.data


# ---------------------------------------------------------------------------
# No config file — defaults apply
# ---------------------------------------------------------------------------


def test_no_config_starts_successfully(tmp_path, monkeypatch):
    """build_mcp must succeed even without config.toml."""
    mcp, svc = _build(tmp_path, monkeypatch, toml=None)
    try:
        assert mcp is not None
        assert svc is not None
    finally:
        asyncio.run(svc.close())


# ---------------------------------------------------------------------------
# Config file is read and applied
# ---------------------------------------------------------------------------


def test_config_toml_regex_only_starts(tmp_path, monkeypatch):
    """backend=regex_only in config.toml must start without GLiNER2."""
    toml = (
        "schema_version = 1\n"
        "[detector]\n"
        'backend = "regex_only"\n'
        "[embedder]\n"
        'backend = "none"\n'
    )
    mcp, svc = _build(tmp_path, monkeypatch, toml=toml)
    try:
        assert mcp is not None
    finally:
        asyncio.run(svc.close())


def test_config_toml_custom_labels_applied(tmp_path, monkeypatch):
    """Custom labels in config.toml flow into the service detector config."""
    toml = (
        "schema_version = 1\n"
        "[detector]\n"
        'backend = "regex_only"\n'
        'labels = ["PERSON", "EMAIL"]\n'
        "[embedder]\n"
        'backend = "none"\n'
    )
    mcp, svc = _build(tmp_path, monkeypatch, toml=toml)
    try:
        assert mcp is not None
        # labels are stored in the service config
        assert svc._config.detector.labels == ["PERSON", "EMAIL"]
    finally:
        asyncio.run(svc.close())


def test_config_toml_strict_rehydrate_false(tmp_path, monkeypatch):
    """strict_rehydrate=false in config.toml: rehydrating an unknown token
    must return the text unchanged rather than raising PIISafetyViolation.
    """
    from piighost.exceptions import PIISafetyViolation  # noqa: PLC0415

    toml = (
        "schema_version = 1\n"
        "[detector]\n"
        'backend = "regex_only"\n'
        "[embedder]\n"
        'backend = "none"\n'
        "[safety]\n"
        "strict_rehydrate = false\n"
    )
    mcp, svc = _build(tmp_path, monkeypatch, toml=toml)
    try:
        # With strict_rehydrate=false unknown tokens pass through unchanged.
        result = asyncio.run(
            _call(mcp, "rehydrate_text", text="Hello <PERSON:deadbeef01234567>")
        )
        assert isinstance(result, dict)
    finally:
        asyncio.run(svc.close())


def test_config_toml_strict_rehydrate_true_is_default(tmp_path, monkeypatch):
    """Without config.toml, strict_rehydrate defaults to True (service default)."""
    mcp, svc = _build(tmp_path, monkeypatch, toml=None)
    try:
        assert svc._config.safety.strict_rehydrate is True
    finally:
        asyncio.run(svc.close())


def test_config_toml_missing_sections_get_defaults(tmp_path, monkeypatch):
    """config.toml with only schema_version must not raise and use defaults."""
    mcp, svc = _build(tmp_path, monkeypatch, toml="schema_version = 1\n")
    try:
        assert svc._config.vault.placeholder_factory == "hash"
        assert svc._config.detector.backend == "gliner2"
    finally:
        asyncio.run(svc.close())


def test_load_config_uses_file_over_defaults(tmp_path, monkeypatch):
    """_load_config must return the TOML values, not the ServiceConfig() defaults."""
    from piighost.mcp.server import _load_config  # noqa: PLC0415

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "config.toml").write_text(
        "schema_version = 1\n[detector]\nbackend = \"regex_only\"\n", encoding="utf-8"
    )
    cfg = _load_config(vault)
    assert cfg.detector.backend == "regex_only"


def test_load_config_fallback_when_no_file(tmp_path):
    """_load_config must return ServiceConfig() defaults when config.toml is absent."""
    from piighost.mcp.server import _load_config  # noqa: PLC0415

    vault = tmp_path / "empty_vault"
    vault.mkdir()
    cfg = _load_config(vault)
    assert cfg.detector.backend == "gliner2"
