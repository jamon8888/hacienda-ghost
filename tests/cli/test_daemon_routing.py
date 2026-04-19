"""End-to-end: CLI should route through a running daemon, or fall back."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app
from piighost.daemon.client import DaemonClient
from piighost.daemon.lifecycle import ensure_daemon, stop_daemon


def _env(tmp_path: Path) -> dict[str, str]:
    return {"PIIGHOST_CWD": str(tmp_path), "PIIGHOST_DETECTOR": "stub"}


def test_cli_routes_anonymize_through_daemon(
    tmp_path: Path, monkeypatch
) -> None:
    """When a daemon is running, `anonymize` RPCs into the daemon process.

    We prove routing by: (a) starting the daemon explicitly, (b) running
    `anonymize`, (c) asserting the daemon's vault.db holds the entities
    by querying vault_stats via a DaemonClient (which talks to the same
    daemon PID that handled the anonymize call).
    """
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    env = _env(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["init"], env=env).exit_code == 0

    vault_dir = tmp_path / ".piighost"
    ensure_daemon(vault_dir, timeout_sec=15.0)
    try:
        result = runner.invoke(
            app,
            ["anonymize", "-"],
            input="Alice lives in Paris",
            env=env,
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert "Alice" not in payload["anonymized"]
        assert payload["anonymized"].count("<PERSON:") == 1

        # The daemon (separate PID) should now report the entities it
        # persisted via RPC. If routing had fallen back to in-process,
        # two distinct Vault instances would have opened and the
        # daemon-side stats would still be empty.
        client = DaemonClient.from_vault(vault_dir)
        assert client is not None
        stats = client.call("vault_stats")
        assert stats["total"] == 2
        assert stats["by_label"]["PERSON"] == 1
        assert stats["by_label"]["LOC"] == 1

        # Daemon log should show RPC activity (Starlette access logs).
        log_path = vault_dir / "daemon.log"
        assert log_path.exists()
    finally:
        stop_daemon(vault_dir)


def test_cli_falls_back_without_daemon(tmp_path: Path, monkeypatch) -> None:
    """With no daemon running, `anonymize` uses the in-process fallback."""
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    env = _env(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["init"], env=env).exit_code == 0

    vault_dir = tmp_path / ".piighost"
    assert not (vault_dir / "daemon.json").exists()

    result = runner.invoke(
        app,
        ["anonymize", "-"],
        input="Alice lives in Paris",
        env=env,
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert "Alice" not in payload["anonymized"]
    assert payload["anonymized"].count("<PERSON:") == 1
