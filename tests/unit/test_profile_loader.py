"""Tests for the bundled profession profile loader."""
from __future__ import annotations

import pytest

from piighost.compliance.profile_loader import load_bundled_profile


def test_load_avocat_profile():
    profile = load_bundled_profile("avocat")
    assert profile["controller"]["profession"] == "avocat"
    assert "Conseil et représentation juridique" in profile["defaults"]["finalites"]


def test_load_each_profession_returns_controller_and_defaults():
    for prof in ("avocat", "notaire", "medecin", "expert_comptable", "rh", "generic"):
        profile = load_bundled_profile(prof)
        assert "controller" in profile, prof
        assert "defaults" in profile, prof
        assert profile["controller"]["profession"] == prof


def test_load_unknown_profession_returns_empty_dict():
    assert load_bundled_profile("zorblax") == {}


def test_load_rejects_path_traversal():
    """profession is user-input — must not escape the bundled dir."""
    assert load_bundled_profile("../etc/passwd") == {}
    assert load_bundled_profile("avocat/../../etc") == {}


def test_load_rejects_empty_string():
    assert load_bundled_profile("") == {}
