from __future__ import annotations

from pathlib import Path

import pytest

from piighost.install.interactive import build_plan_interactively
from piighost.install.plan import Client, Embedder, Mode


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    return tmp_path


def _scripted(answers):
    """Make a fake `_ask`-like callable that returns answers in order."""
    it = iter(answers)

    def _ask(prompt, **kw):
        return next(it)

    return _ask


def test_default_full_flow(isolated_home, monkeypatch):
    answers = ["1", "1,2", "", "1", "y"]
    monkeypatch.setattr(
        "piighost.install.interactive._ask", _scripted(answers)
    )
    plan = build_plan_interactively(starting_defaults=None)
    assert plan.mode is Mode.FULL
    assert plan.clients == frozenset({Client.CLAUDE_CODE, Client.CLAUDE_DESKTOP})
    assert plan.embedder is Embedder.LOCAL


def test_mcp_only_no_clients(isolated_home, monkeypatch):
    answers = ["2", "", "", "1", "y"]  # mcp-only, no clients, default vault, local
    monkeypatch.setattr(
        "piighost.install.interactive._ask", _scripted(answers)
    )
    plan = build_plan_interactively(starting_defaults=None)
    assert plan.mode is Mode.MCP_ONLY
    assert plan.clients == frozenset()
    assert plan.install_user_service is False


def test_mistral_prompts_for_key(isolated_home, monkeypatch):
    answers = ["1", "1", "", "2", "sk-test", "y"]
    monkeypatch.setattr(
        "piighost.install.interactive._ask", _scripted(answers)
    )
    plan = build_plan_interactively(starting_defaults=None)
    assert plan.embedder is Embedder.MISTRAL
    assert plan.mistral_api_key == "sk-test"


def test_user_aborts_at_review(isolated_home, monkeypatch):
    answers = ["1", "1", "", "1", "n"]
    monkeypatch.setattr(
        "piighost.install.interactive._ask", _scripted(answers)
    )
    with pytest.raises(SystemExit):
        build_plan_interactively(starting_defaults=None)
