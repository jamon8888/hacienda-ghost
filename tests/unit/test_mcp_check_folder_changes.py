from __future__ import annotations

import asyncio

import pytest

from piighost.mcp.server import build_mcp


@pytest.fixture()
def mcp_svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    mcp, svc = asyncio.run(build_mcp(tmp_path / "vault"))
    yield mcp, svc
    asyncio.run(svc.close())


def test_check_folder_changes_tool_is_registered(mcp_svc):
    mcp, _ = mcp_svc
    tool_list = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tool_list}
    assert "check_folder_changes" in tool_names
