from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app


def test_init_creates_piighost_dir(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init"], env={"PIIGHOST_CWD": str(tmp_path)})
    assert result.exit_code == 0
    assert (tmp_path / ".piighost" / "config.toml").exists()
    assert (tmp_path / ".piighost" / "vault.db").exists()


def test_init_is_idempotent(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(app, ["init"], env={"PIIGHOST_CWD": str(tmp_path)})
    result = runner.invoke(app, ["init"], env={"PIIGHOST_CWD": str(tmp_path)})
    # Default: second run refuses unless --force; exit_code != 0 acceptable
    assert result.exit_code in (0, 2)
