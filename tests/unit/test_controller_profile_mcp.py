"""Tests for controller_profile_get / set MCP dispatchers on PIIGhostService."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.core import PIIGhostService
from piighost.service.config import ServiceConfig, RerankerSection


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    # Redirect Path.home() / HOME / USERPROFILE to a tmp dir so the
    # ControllerProfileService writes to a sandbox instead of the
    # developer's real ~/.piighost/. Without this, a stale global
    # profile from a previous test run leaks into the test.
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


def test_controller_profile_get_global_returns_empty_when_missing(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    profile = asyncio.run(svc.controller_profile_get(scope="global"))
    assert profile == {}
    asyncio.run(svc.close())


def test_controller_profile_set_then_get_global(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    payload = {
        "controller": {"name": "Cabinet X", "profession": "avocat"},
        "defaults": {"finalites": ["Conseil juridique"]},
    }
    asyncio.run(svc.controller_profile_set(profile=payload, scope="global"))
    got = asyncio.run(svc.controller_profile_get(scope="global"))
    assert got["controller"]["name"] == "Cabinet X"
    assert got["controller"]["profession"] == "avocat"
    asyncio.run(svc.close())


def test_controller_profile_per_project_override(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={"controller": {"name": "Global", "profession": "avocat"}},
        scope="global",
    ))
    asyncio.run(svc.controller_profile_set(
        profile={"controller": {"name": "Project-Specific"}},
        scope="project", project="dossier-x",
    ))
    merged = asyncio.run(svc.controller_profile_get(
        scope="project", project="dossier-x",
    ))
    assert merged["controller"]["name"] == "Project-Specific"
    assert merged["controller"]["profession"] == "avocat"  # inherited
    asyncio.run(svc.close())


def test_controller_profile_set_requires_project_when_scope_project(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(svc.controller_profile_set(
            profile={"x": "y"}, scope="project",
        ))
    asyncio.run(svc.close())
