import json
from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app


def test_anonymize_stdin(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(app, ["init"], env={"PIIGHOST_CWD": str(tmp_path)})
    # We inject stubs for detector and embedder via env vars (see service loader).
    # PIIGHOST_EMBEDDER=stub prevents sentence_transformers from being imported
    # by LocalEmbedder when the indexing subsystem initialises.
    result = runner.invoke(
        app,
        ["anonymize", "-"],
        input="Alice lives in Paris",
        env={
            "PIIGHOST_CWD": str(tmp_path),
            "PIIGHOST_DETECTOR": "stub",
            "PIIGHOST_EMBEDDER": "stub",
        },
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert "Alice" not in payload["anonymized"]
    assert payload["anonymized"].count("<PERSON:") == 1
