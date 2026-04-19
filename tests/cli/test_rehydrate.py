import json
from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app


def test_rehydrate_roundtrip(tmp_path: Path) -> None:
    runner = CliRunner()
    env = {"PIIGHOST_CWD": str(tmp_path), "PIIGHOST_DETECTOR": "stub"}
    runner.invoke(app, ["init"], env=env)
    a = runner.invoke(app, ["anonymize", "-"], input="Alice in Paris", env=env)
    anon = json.loads(a.stdout.strip().splitlines()[-1])["anonymized"]
    r = runner.invoke(app, ["rehydrate", "-"], input=anon, env=env)
    assert r.exit_code == 0
    payload = json.loads(r.stdout.strip().splitlines()[-1])
    assert payload["text"] == "Alice in Paris"
