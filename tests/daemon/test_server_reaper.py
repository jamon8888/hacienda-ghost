"""The daemon spawns the reaper task on startup and runs it periodically."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from piighost.daemon.server import build_app


@pytest.mark.asyncio
async def test_reaper_runs_on_startup(tmp_path) -> None:
    with patch("piighost.daemon.server.reaper.reap", return_value=[]) as mock_reap:
        app, _token = build_app(tmp_path)
        with TestClient(app) as _:
            # TestClient triggers lifespan; reaper should have run at least once.
            await asyncio.sleep(0.2)
        assert mock_reap.call_count >= 1


@pytest.mark.asyncio
async def test_reaper_logs_killed_pids(tmp_path) -> None:
    with patch("piighost.daemon.server.reaper.reap", return_value=[7708, 15732]):
        app, _token = build_app(tmp_path)
        with TestClient(app) as _:
            await asyncio.sleep(0.2)
    log = (tmp_path / "daemon.log").read_text(encoding="utf-8")
    assert "reaper_killed" in log
    assert "7708" in log
    assert "15732" in log
