from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_doctor_exits_nonzero_when_no_proxy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    r = runner.invoke(app, ["doctor"])
    # Proxy not installed → doctor reports missing components but does not crash.
    assert r.exit_code != 0
    assert "proxy" in r.stdout.lower()
