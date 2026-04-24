# tests/install/test_hosts_file.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from piighost.install.hosts_file import add_redirect, has_redirect, remove_redirect


def _make_hosts(tmp_path: Path, content: str = "") -> Path:
    p = tmp_path / "hosts"
    p.write_text(content, encoding="utf-8")
    return p


def test_add_redirect_inserts_sentinel_block(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path, "127.0.0.1 localhost\n")
    add_redirect("api.anthropic.com", hosts_path=hosts)
    text = hosts.read_text(encoding="utf-8")
    assert "# BEGIN piighost" in text
    assert "127.0.0.1 api.anthropic.com" in text
    assert "# END piighost" in text


def test_has_redirect_true_after_add(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path)
    add_redirect("api.anthropic.com", hosts_path=hosts)
    assert has_redirect("api.anthropic.com", hosts_path=hosts) is True


def test_has_redirect_false_on_empty(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path)
    assert has_redirect("api.anthropic.com", hosts_path=hosts) is False


def test_remove_redirect_strips_sentinel(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path, "127.0.0.1 localhost\n")
    add_redirect("api.anthropic.com", hosts_path=hosts)
    remove_redirect("api.anthropic.com", hosts_path=hosts)
    text = hosts.read_text(encoding="utf-8")
    assert "BEGIN piighost" not in text
    assert "api.anthropic.com" not in text
    assert "127.0.0.1 localhost" in text


def test_add_redirect_is_idempotent(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path)
    add_redirect("api.anthropic.com", hosts_path=hosts)
    add_redirect("api.anthropic.com", hosts_path=hosts)
    text = hosts.read_text(encoding="utf-8")
    assert text.count("# BEGIN piighost") == 1


def test_add_redirect_creates_backup(tmp_path: Path) -> None:
    original = "127.0.0.1 localhost\n"
    hosts = _make_hosts(tmp_path, original)
    add_redirect("api.anthropic.com", hosts_path=hosts)
    bak = hosts.with_suffix(".piighost.bak")
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == original


def test_remove_redirect_noop_on_missing_file(tmp_path: Path) -> None:
    hosts = tmp_path / "no_such_hosts"
    remove_redirect("api.anthropic.com", hosts_path=hosts)  # must not raise


def test_has_redirect_false_on_missing_file(tmp_path: Path) -> None:
    hosts = tmp_path / "no_such_hosts"
    assert has_redirect("api.anthropic.com", hosts_path=hosts) is False
