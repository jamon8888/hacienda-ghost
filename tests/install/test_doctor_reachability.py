from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app


runner = CliRunner()


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def _seed_base_url(home: Path) -> None:
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({
        "env": {"ANTHROPIC_BASE_URL": "https://localhost:8443"}
    }))


def test_doctor_warns_when_base_url_set_but_proxy_unreachable(isolated_home):
    _seed_base_url(isolated_home)
    with patch(
        "piighost.cli.commands.doctor._proxy_reachable", return_value=False
    ):
        result = runner.invoke(app, ["doctor"])
    assert "[FAIL]" in result.output
    assert "8443" in result.output
    assert "piighost disconnect" in result.output


def test_doctor_silent_when_no_base_url_set(isolated_home):
    # No settings.json present — doctor should not complain about the proxy
    with patch(
        "piighost.cli.commands.doctor._proxy_reachable", return_value=False
    ):
        result = runner.invoke(app, ["doctor"])
    assert "8443" not in result.output
