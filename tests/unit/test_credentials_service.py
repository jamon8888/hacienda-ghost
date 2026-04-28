"""CredentialsService — credentials.toml lifecycle."""
from __future__ import annotations

import os
import sys

import pytest

from piighost.service.credentials import CredentialsService


@pytest.fixture()
def cred_root(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return home


def test_no_file_returns_empty(cred_root):
    s = CredentialsService()
    assert s.get_openlegi_token() is None
    assert not s.has_openlegi_token()


def test_set_then_get_token(cred_root):
    s = CredentialsService()
    s.set_openlegi_token("piste-token-xyz")
    assert s.get_openlegi_token() == "piste-token-xyz"
    assert s.has_openlegi_token() is True


def test_credentials_file_created_with_strict_perms(cred_root):
    s = CredentialsService()
    s.set_openlegi_token("x")
    path = cred_root / ".piighost" / "credentials.toml"
    assert path.exists()
    if sys.platform != "win32":
        # 600 = rw-------
        assert oct(path.stat().st_mode)[-3:] == "600"


def test_unset_removes_token(cred_root):
    s = CredentialsService()
    s.set_openlegi_token("x")
    s.unset_openlegi_token()
    assert s.get_openlegi_token() is None
    assert not s.has_openlegi_token()


def test_summary_never_returns_token_text(cred_root):
    """summary() is what controller_profile_get-style callers see —
    NEVER the actual token value."""
    s = CredentialsService()
    s.set_openlegi_token("super-secret-token")
    summary = s.summary()
    assert summary == {"openlegi": {"configured": True}}
    serialized = repr(summary)
    assert "super-secret-token" not in serialized


def test_set_overwrites_existing(cred_root):
    s = CredentialsService()
    s.set_openlegi_token("first")
    s.set_openlegi_token("second")
    assert s.get_openlegi_token() == "second"
