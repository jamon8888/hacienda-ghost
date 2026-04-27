"""Service-level test for controller_profile_defaults MCP dispatcher."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_controller_profile_defaults_returns_avocat(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    profile = asyncio.run(svc.controller_profile_defaults(profession="avocat"))
    assert profile["controller"]["profession"] == "avocat"
    assert "finalites" in profile["defaults"]
    asyncio.run(svc.close())


def test_controller_profile_defaults_unknown_returns_empty(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    profile = asyncio.run(svc.controller_profile_defaults(profession="zorblax"))
    assert profile == {}
    asyncio.run(svc.close())


def test_controller_profile_defaults_rejects_path_traversal(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    profile = asyncio.run(svc.controller_profile_defaults(profession="../etc/passwd"))
    assert profile == {}
    asyncio.run(svc.close())


def test_controller_profile_defaults_each_profession(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    for prof in ("avocat", "notaire", "medecin", "expert_comptable", "rh", "generic"):
        profile = asyncio.run(svc.controller_profile_defaults(profession=prof))
        assert profile.get("controller", {}).get("profession") == prof, prof
    asyncio.run(svc.close())
