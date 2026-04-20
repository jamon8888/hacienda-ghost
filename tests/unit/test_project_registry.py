import time

import pytest

from piighost.vault.project_registry import (
    ProjectRegistry,
    ProjectInfo,
    InvalidProjectName,
)


def _open(tmp_path):
    return ProjectRegistry.open(tmp_path / "projects.db")


def test_open_creates_empty_registry(tmp_path):
    r = _open(tmp_path)
    assert r.list() == []
    r.close()


def test_create_and_get(tmp_path):
    r = _open(tmp_path)
    info = r.create("client-a", description="Client A docs")
    assert info.name == "client-a"
    assert info.description == "Client A docs"
    assert info.placeholder_salt == "client-a"
    assert info.created_at > 0
    got = r.get("client-a")
    assert got == info
    r.close()


def test_create_with_custom_salt(tmp_path):
    r = _open(tmp_path)
    info = r.create("client-a", description="", placeholder_salt="")
    assert info.placeholder_salt == ""
    r.close()


def test_exists(tmp_path):
    r = _open(tmp_path)
    assert r.exists("client-a") is False
    r.create("client-a")
    assert r.exists("client-a") is True
    r.close()


def test_duplicate_create_raises(tmp_path):
    r = _open(tmp_path)
    r.create("client-a")
    with pytest.raises(ValueError, match="already exists"):
        r.create("client-a")
    r.close()


def test_list_returns_all(tmp_path):
    r = _open(tmp_path)
    r.create("client-a")
    r.create("client-b")
    names = {p.name for p in r.list()}
    assert names == {"client-a", "client-b"}
    r.close()


def test_delete(tmp_path):
    r = _open(tmp_path)
    r.create("client-a")
    assert r.delete("client-a") is True
    assert r.exists("client-a") is False
    assert r.delete("client-a") is False
    r.close()


def test_touch_updates_last_accessed(tmp_path):
    r = _open(tmp_path)
    r.create("client-a")
    info1 = r.get("client-a")
    time.sleep(1.1)
    r.touch("client-a")
    info2 = r.get("client-a")
    assert info2.last_accessed_at > info1.last_accessed_at
    r.close()


@pytest.mark.parametrize("invalid", [
    "",
    "with space",
    "../escape",
    "slash/inside",
    "dot.inside",
    "emoji-\N{GRINNING FACE}",
    "a" * 65,
])
def test_invalid_name_rejected(tmp_path, invalid):
    r = _open(tmp_path)
    with pytest.raises(InvalidProjectName):
        r.create(invalid)
    r.close()


@pytest.mark.parametrize("valid", [
    "client-a",
    "client_b",
    "CLIENT_42",
    "a",
    "a" * 64,
])
def test_valid_names_accepted(tmp_path, valid):
    r = _open(tmp_path)
    r.create(valid)
    assert r.exists(valid)
    r.close()
