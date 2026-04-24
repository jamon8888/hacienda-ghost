from __future__ import annotations

from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_proxy_help_shows_subcommands() -> None:
    r = runner.invoke(app, ["proxy", "--help"])
    assert r.exit_code == 0
    assert "run" in r.stdout
    assert "status" in r.stdout
