"""profile_loader logs a warning when a bundled TOML fails to parse.

Closes Phase 4 followup #3. Silent swallow → caplog visibility.
"""
from __future__ import annotations

import logging

import pytest

from piighost.compliance import profile_loader as plm


def test_corrupt_bundled_toml_emits_warning(monkeypatch, tmp_path, caplog):
    """If reading or parsing the bundled TOML raises, a warning is logged."""
    # Force the loader's resources path to a tmp dir with a corrupt TOML.
    bad_dir = tmp_path / "profiles"
    bad_dir.mkdir()
    bad_toml = bad_dir / "broken.toml"
    bad_toml.write_text("this is not [valid TOML\n", encoding="utf-8")

    class _FakeResources:
        @staticmethod
        def files(_):
            return bad_dir

    monkeypatch.setattr(plm, "resources", _FakeResources())

    caplog.set_level(logging.WARNING, logger="piighost.compliance.profile_loader")
    result = plm.load_bundled_profile("broken")
    assert result == {}
    # Warning was emitted
    matching = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("broken" in r.getMessage() for r in matching), (
        f"Expected warning mentioning 'broken'; got {[r.getMessage() for r in matching]}"
    )


def test_unknown_profession_does_not_warn(monkeypatch, caplog):
    """Returning {} for an unknown (but well-formed) profession is silent —
    no warning, no error. That's not a bug, it's normal flow."""
    caplog.set_level(logging.WARNING, logger="piighost.compliance.profile_loader")
    result = plm.load_bundled_profile("zorblax")
    assert result == {}
    matching = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert matching == [], (
        f"Unexpected warnings for unknown profession: {[r.getMessage() for r in matching]}"
    )
