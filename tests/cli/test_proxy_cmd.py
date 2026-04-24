from __future__ import annotations

import datetime
from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_proxy_help_shows_subcommands() -> None:
    r = runner.invoke(app, ["proxy", "--help"])
    assert r.exit_code == 0
    assert "run" in r.stdout
    assert "status" in r.stdout


def test_proxy_logs_shows_last_n_lines(tmp_path: Path) -> None:
    now = datetime.datetime.now()
    month_dir = tmp_path / ".piighost" / "audit" / f"{now.year}-{now.month:02d}"
    month_dir.mkdir(parents=True)
    log_file = month_dir / "sessions.ndjson"
    entries = [f'{{"ts": "2026-04-24T{i:02d}:00:00Z", "status": "ok"}}' for i in range(5)]
    log_file.write_text("\n".join(entries), encoding="utf-8")

    r = runner.invoke(
        app,
        ["proxy", "logs", "--vault", str(tmp_path / ".piighost"), "--tail", "3"],
    )
    assert r.exit_code == 0, f"stdout: {r.stdout}"
    assert entries[2] in r.stdout
    assert entries[3] in r.stdout
    assert entries[4] in r.stdout
    assert entries[0] not in r.stdout
    assert entries[1] not in r.stdout


def test_proxy_logs_exits_nonzero_when_no_log(tmp_path: Path) -> None:
    r = runner.invoke(app, ["proxy", "logs", "--vault", str(tmp_path / ".piighost")])
    assert r.exit_code != 0


def test_proxy_help_shows_logs() -> None:
    r = runner.invoke(app, ["proxy", "--help"])
    assert "logs" in r.stdout
