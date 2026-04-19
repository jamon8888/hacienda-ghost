import json
from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app


def test_daemon_start_status_stop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    env = {"PIIGHOST_CWD": str(tmp_path), "PIIGHOST_DETECTOR": "stub"}
    runner = CliRunner()
    runner.invoke(app, ["init"], env=env)

    start = runner.invoke(app, ["daemon", "start"], env=env)
    assert start.exit_code == 0
    info = json.loads(start.stdout.strip())
    assert "pid" in info and "port" in info

    stat = runner.invoke(app, ["daemon", "status"], env=env)
    assert stat.exit_code == 0
    assert json.loads(stat.stdout.strip())["running"] is True

    stop = runner.invoke(app, ["daemon", "stop"], env=env)
    assert stop.exit_code == 0

    stat2 = runner.invoke(app, ["daemon", "status"], env=env)
    assert json.loads(stat2.stdout.strip())["running"] is False
