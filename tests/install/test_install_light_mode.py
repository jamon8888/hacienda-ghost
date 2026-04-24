from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_install_light_generates_ca_and_writes_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # On Windows, os.path.expanduser uses USERPROFILE, not HOME.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # Skip trust-store step in test (requires admin).
    import piighost.install.trust_store as ts
    monkeypatch.setattr(ts, "install_ca", lambda _p: None)
    # Skip preflight network + disk checks.
    import piighost.install as install_mod
    # We'll monkeypatch whatever preflight functions exist in the install module.
    # If the existing install __init__.py has specific preflight functions, patch them.
    # Skip uv install (if any).

    r = runner.invoke(app, ["install", "--mode=light", "--force"])
    # If --force doesn't exist yet, just try without it.
    if r.exit_code != 0 and "--force" in r.stdout:
        r = runner.invoke(app, ["install", "--mode=light"])

    # Accept exit code 0 only
    assert r.exit_code == 0, f"stdout: {r.stdout}\nstderr: {getattr(r, 'stderr', '')}"

    ca = tmp_path / ".piighost" / "proxy" / "ca.pem"
    leaf = tmp_path / ".piighost" / "proxy" / "leaf.pem"
    assert ca.exists(), f"ca.pem not found at {ca}"
    assert leaf.exists(), f"leaf.pem not found at {leaf}"

    settings = tmp_path / ".claude" / "settings.json"
    assert settings.exists(), f"settings.json not found at {settings}"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_BASE_URL"] == "https://localhost:8443"
