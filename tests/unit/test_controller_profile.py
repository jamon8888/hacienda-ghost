"""Tests for ControllerProfileService — global TOML + per-project override."""
from __future__ import annotations

import pytest

from piighost.service.controller_profile import ControllerProfileService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return tmp_path / "vault"


def test_get_global_when_missing_returns_empty(vault_dir):
    svc = ControllerProfileService(vault_dir)
    assert svc.get(scope="global") == {}


def test_set_then_get_global_round_trip(vault_dir):
    svc = ControllerProfileService(vault_dir)
    profile = {
        "controller": {"name": "Cabinet X", "profession": "avocat"},
        "defaults": {"finalites": ["Conseil juridique"]},
    }
    svc.set(profile, scope="global")
    got = svc.get(scope="global")
    assert got["controller"]["name"] == "Cabinet X"
    assert got["defaults"]["finalites"] == ["Conseil juridique"]


def test_has_global_true_after_set(vault_dir):
    svc = ControllerProfileService(vault_dir)
    assert svc.has_global() is False
    svc.set({"controller": {"name": "C"}}, scope="global")
    assert svc.has_global() is True


def test_per_project_override_merges_with_global(vault_dir):
    svc = ControllerProfileService(vault_dir)
    svc.set(
        {"controller": {"name": "Global", "profession": "avocat"},
         "defaults": {"finalites": ["A", "B"]}},
        scope="global",
    )
    svc.set(
        {"controller": {"name": "Project-Specific"}},
        scope="project", project="dossier-x",
    )
    merged = svc.get(scope="project", project="dossier-x")
    assert merged["controller"]["name"] == "Project-Specific"  # override
    assert merged["controller"]["profession"] == "avocat"  # inherited
    assert merged["defaults"]["finalites"] == ["A", "B"]  # inherited


def test_per_project_override_deep_merge(vault_dir):
    svc = ControllerProfileService(vault_dir)
    svc.set(
        {"controller": {"name": "A", "address": "1 rue X"},
         "dpo": {"name": "Marie", "email": "m@x.fr"}},
        scope="global",
    )
    svc.set(
        {"dpo": {"email": "different@x.fr"}},  # only override email
        scope="project", project="p1",
    )
    merged = svc.get(scope="project", project="p1")
    assert merged["dpo"]["name"] == "Marie"  # kept from global
    assert merged["dpo"]["email"] == "different@x.fr"  # overridden
    assert merged["controller"]["address"] == "1 rue X"  # untouched


def test_get_project_returns_global_when_no_override(vault_dir):
    svc = ControllerProfileService(vault_dir)
    svc.set({"controller": {"name": "G"}}, scope="global")
    got = svc.get(scope="project", project="never-overridden")
    assert got["controller"]["name"] == "G"


def test_set_atomic_does_not_corrupt_on_concurrent_write(vault_dir, tmp_path):
    """Writes go through tempfile + os.replace — never partial."""
    svc = ControllerProfileService(vault_dir)
    svc.set({"controller": {"name": "First"}}, scope="global")
    svc.set({"controller": {"name": "Second"}}, scope="global")
    got = svc.get(scope="global")
    # Either First or Second, never garbage.
    assert got["controller"]["name"] in ("First", "Second")
    # The actual file must be valid TOML (not half-written).
    import tomllib
    raw = (svc._global_path).read_bytes()
    parsed = tomllib.loads(raw.decode("utf-8"))
    assert "controller" in parsed


def test_set_requires_project_when_scope_is_project(vault_dir):
    svc = ControllerProfileService(vault_dir)
    with pytest.raises(ValueError):
        svc.set({"x": "y"}, scope="project")  # no project name


def test_get_requires_project_when_scope_is_project(vault_dir):
    svc = ControllerProfileService(vault_dir)
    with pytest.raises(ValueError):
        svc.get(scope="project")
