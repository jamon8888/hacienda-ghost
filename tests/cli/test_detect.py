import json
from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app


def test_detect_emits_detections(tmp_path: Path) -> None:
    runner = CliRunner()
    env = {"PIIGHOST_CWD": str(tmp_path), "PIIGHOST_DETECTOR": "stub"}
    runner.invoke(app, ["init"], env=env)
    r = runner.invoke(app, ["detect", "-"], input="Alice lives in Paris", env=env)
    assert r.exit_code == 0
    payload = json.loads(r.stdout.strip().splitlines()[-1])
    labels = {d["label"] for d in payload["detections"]}
    assert "PERSON" in labels
    assert "LOC" in labels
