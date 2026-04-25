"""piighost cleanup CLI behaviors."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_dry_run_default_does_not_modify_anything(tmp_path: Path) -> None:
    stale = tmp_path / "daemon.json"
    stale.write_text(json.dumps({"pid": 999_999, "port": 0, "token": "x", "started_at": 0}))
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path)])
    assert r.exit_code == 0
    assert stale.exists(), "dry-run must not delete anything"
    assert "stale" in r.stdout.lower()


def test_force_removes_stale_handshake(tmp_path: Path) -> None:
    stale = tmp_path / "daemon.json"
    stale.write_text(json.dumps({"pid": 999_999, "port": 0, "token": "x", "started_at": 0}))
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path), "--force"])
    assert r.exit_code == 0
    assert not stale.exists()


def test_keeps_live_handshake(tmp_path: Path) -> None:
    """Handshake with a live PID (this test process) must not be removed."""
    live = tmp_path / "daemon.json"
    live.write_text(json.dumps({
        "pid": os.getpid(), "port": 51207, "token": "x", "started_at": 0,
    }))
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path), "--force"])
    assert r.exit_code == 0
    assert live.exists()


def test_reports_orphan_shims(tmp_path: Path) -> None:
    with patch("piighost.cli.commands.cleanup.reaper.reap", return_value=[7708, 15732]):
        r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path), "--force"])
    assert r.exit_code == 0
    assert "7708" in r.stdout
    assert "15732" in r.stdout


def test_json_output(tmp_path: Path) -> None:
    stale = tmp_path / "daemon.json"
    stale.write_text(json.dumps({"pid": 999_999, "port": 0, "token": "x", "started_at": 0}))
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path), "--force", "--json"])
    assert r.exit_code == 0
    payload = json.loads(r.stdout)
    assert "removed" in payload
    assert any("daemon.json" in item for item in payload["removed"])


def test_warns_on_disabled_flag_without_recent_stop(tmp_path: Path) -> None:
    (tmp_path / "daemon.disabled").touch()
    # No daemon.log exists, so "no recent stop event"
    r = runner.invoke(app, ["cleanup", "--vault", str(tmp_path)])
    assert "daemon.disabled" in r.stdout
    assert "warn" in r.stdout.lower()
    # Flag is NOT auto-removed
    assert (tmp_path / "daemon.disabled").exists()
