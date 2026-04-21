"""Smoke-tests that the core CLI commands expose the ``--project`` flag.

These tests read Typer's rendered ``--help`` text. Typer defers rendering to
Rich, which wraps against ``COLUMNS`` (default 80 on many CI runners). At 80
columns, option names like ``--project`` get wrapped off-screen and the raw
``result.output`` no longer contains the literal string, even though the
option is registered. Force a wide terminal so we assert on semantics, not
on incidental wrapping.
"""
from __future__ import annotations

from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()

# Wide enough that Rich never wraps long option names off-screen on any CI
# runner (GitHub Actions Ubuntu/Windows/macOS default to 80).
_WIDE_ENV = {"COLUMNS": "200", "TERM": "dumb"}


def _help(*argv: str) -> str:
    result = runner.invoke(app, [*argv, "--help"], env=_WIDE_ENV)
    assert result.exit_code == 0, result.output
    return result.output


def test_anonymize_has_project_flag() -> None:
    assert "--project" in _help("anonymize")


def test_query_has_project_flag() -> None:
    assert "--project" in _help("query")


def test_index_has_project_flag() -> None:
    assert "--project" in _help("index")


def test_vault_list_has_project_flag() -> None:
    assert "--project" in _help("vault", "list")


def test_rm_has_project_flag() -> None:
    assert "--project" in _help("rm")


def test_index_status_has_project_flag() -> None:
    assert "--project" in _help("index-status")


def test_rehydrate_has_project_flag() -> None:
    assert "--project" in _help("rehydrate")


def test_projects_list_command_exists() -> None:
    _help("projects", "list")


def test_projects_create_command_exists() -> None:
    assert "name" in _help("projects", "create").lower()


def test_projects_delete_command_exists() -> None:
    _help("projects", "delete")
