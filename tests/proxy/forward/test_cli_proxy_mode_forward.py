"""CLI test: `piighost proxy run --mode=forward` calls forward main."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from piighost.cli.main import app


def test_mode_forward_invokes_forward_main():
    runner = CliRunner()
    with patch("piighost.proxy.forward.__main__.main", return_value=0) as mocked:
        result = runner.invoke(app, ["proxy", "run", "--mode=forward"])

    assert result.exit_code == 0
    mocked.assert_called_once()
