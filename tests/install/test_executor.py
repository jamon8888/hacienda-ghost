from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from piighost.install.executor import execute
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _plan(tmp_path, mode, clients=frozenset(), **overrides):
    base = dict(
        mode=mode,
        vault_dir=tmp_path / "vault",
        embedder=Embedder.LOCAL,
        mistral_api_key=None,
        clients=clients,
        install_user_service=mode is not Mode.MCP_ONLY,
        warmup_models=False,
        force=False,
        dry_run=False,
    )
    base.update(overrides)
    return InstallPlan(**base)


@pytest.fixture
def fakes(monkeypatch):
    fakes = {
        "modes": MagicMock(),
        "clients": MagicMock(),
        "user_service": MagicMock(),
        "models": MagicMock(),
    }
    monkeypatch.setattr("piighost.install.executor.modes", fakes["modes"])
    monkeypatch.setattr("piighost.install.executor.clients_mod", fakes["clients"])
    monkeypatch.setattr(
        "piighost.install.executor.user_service", fakes["user_service"]
    )
    monkeypatch.setattr("piighost.install.executor.models", fakes["models"])
    return fakes


def test_full_plan_runs_light_proxy_then_clients_then_user_service(tmp_path, fakes):
    plan = _plan(tmp_path, Mode.FULL, clients=frozenset({Client.CLAUDE_CODE}))
    execute(plan)
    fakes["modes"].run_light_mode_proxy.assert_called_once_with(plan)
    fakes["clients"].register.assert_called_once_with(plan, Client.CLAUDE_CODE)
    fakes["user_service"].install.assert_called_once()
    fakes["models"].warmup.assert_not_called()  # warmup_models=False


def test_mcp_only_skips_proxy_and_user_service(tmp_path, fakes):
    plan = _plan(
        tmp_path,
        Mode.MCP_ONLY,
        clients=frozenset({Client.CLAUDE_CODE}),
        install_user_service=False,
    )
    execute(plan)
    fakes["modes"].run_light_mode_proxy.assert_not_called()
    fakes["modes"].run_strict_mode_proxy.assert_not_called()
    fakes["modes"].run_mcp_only.assert_called_once_with(plan)
    fakes["clients"].register.assert_called_once_with(plan, Client.CLAUDE_CODE)
    fakes["user_service"].install.assert_not_called()


def test_strict_runs_strict_proxy(tmp_path, fakes):
    plan = _plan(
        tmp_path,
        Mode.STRICT,
        clients=frozenset(),
        install_user_service=True,
    )
    execute(plan)
    fakes["modes"].run_strict_mode_proxy.assert_called_once_with(plan)
    fakes["clients"].register.assert_not_called()


def test_dry_run_prints_and_skips_actions(tmp_path, capsys, fakes):
    plan = _plan(
        tmp_path,
        Mode.FULL,
        clients=frozenset({Client.CLAUDE_CODE}),
        dry_run=True,
    )
    execute(plan)
    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out or "CA" in captured.out
    fakes["modes"].run_light_mode_proxy.assert_not_called()


def test_warmup_runs_when_requested(tmp_path, fakes):
    plan = _plan(
        tmp_path,
        Mode.FULL,
        clients=frozenset(),
        warmup_models=True,
    )
    execute(plan)
    fakes["models"].warmup.assert_called_once()
