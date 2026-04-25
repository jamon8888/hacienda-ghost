"""Tests for `piighost on` / `piighost off` / `piighost status`.

These three commands are the user-facing switch for anonymization. They
manipulate a single flag file (``<vault>/paused``) which the proxy reads
on each request to decide whether to anonymize or transparently forward.

The daemon process keeps running in both states — that's how strict mode
(hosts file redirect) stays healthy while the user toggles anonymization.
"""
from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app
from piighost.proxy.handshake import ProxyHandshake, write_handshake

runner = CliRunner()


def test_on_removes_paused_flag(tmp_path: Path) -> None:
    vault = tmp_path / ".piighost"
    vault.mkdir()
    (vault / "paused").touch()

    r = runner.invoke(app, ["on", "--vault", str(vault)])
    assert r.exit_code == 0, r.stdout
    assert not (vault / "paused").exists()
    assert "ON" in r.stdout.upper()


def test_off_creates_paused_flag(tmp_path: Path) -> None:
    vault = tmp_path / ".piighost"
    vault.mkdir()

    r = runner.invoke(app, ["off", "--vault", str(vault)])
    assert r.exit_code == 0, r.stdout
    assert (vault / "paused").exists()
    assert "OFF" in r.stdout.upper() or "PAUSED" in r.stdout.upper()


def test_on_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / ".piighost"
    vault.mkdir()
    # No flag present — `on` should still succeed.
    r = runner.invoke(app, ["on", "--vault", str(vault)])
    assert r.exit_code == 0
    assert not (vault / "paused").exists()


def test_off_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / ".piighost"
    vault.mkdir()
    (vault / "paused").touch()
    r = runner.invoke(app, ["off", "--vault", str(vault)])
    assert r.exit_code == 0
    assert (vault / "paused").exists()


def test_status_when_service_not_running(tmp_path: Path) -> None:
    vault = tmp_path / ".piighost"
    vault.mkdir()

    r = runner.invoke(app, ["status", "--vault", str(vault)])
    assert r.exit_code != 0
    assert "not running" in r.stdout.lower()


def test_status_when_running_active(tmp_path: Path) -> None:
    vault = tmp_path / ".piighost"
    vault.mkdir()
    write_handshake(vault, ProxyHandshake(pid=os.getpid(), port=8443, token="t"))

    r = runner.invoke(app, ["status", "--vault", str(vault)])
    assert r.exit_code == 0, r.stdout
    out = r.stdout.lower()
    assert "running" in out
    assert "active" in out
    assert str(os.getpid()) in r.stdout
    assert "8443" in r.stdout


def test_status_when_running_paused(tmp_path: Path) -> None:
    vault = tmp_path / ".piighost"
    vault.mkdir()
    write_handshake(vault, ProxyHandshake(pid=os.getpid(), port=8443, token="t"))
    (vault / "paused").touch()

    r = runner.invoke(app, ["status", "--vault", str(vault)])
    assert r.exit_code == 0, r.stdout
    out = r.stdout.lower()
    assert "running" in out
    assert "paused" in out


def test_on_command_help_works() -> None:
    r = runner.invoke(app, ["on", "--help"])
    assert r.exit_code == 0


def test_off_command_help_works() -> None:
    r = runner.invoke(app, ["off", "--help"])
    assert r.exit_code == 0


def test_status_command_help_works() -> None:
    r = runner.invoke(app, ["status", "--help"])
    assert r.exit_code == 0
