from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_query_help_has_filter_prefix():
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--filter-prefix" in result.output


def test_query_help_has_filter_doc_ids():
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--filter-doc-ids" in result.output


def test_query_help_has_rerank():
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--rerank" in result.output


def test_query_help_has_top_n():
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--top-n" in result.output
