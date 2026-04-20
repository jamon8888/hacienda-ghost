import asyncio
import pytest
from pathlib import Path


def test_build_mcp_returns_fastmcp_and_service(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    from piighost.mcp.server import build_mcp
    mcp, svc = asyncio.run(build_mcp(tmp_path / "vault"))
    assert mcp is not None
    assert svc is not None
    asyncio.run(svc.close())


def test_mcp_has_expected_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    from piighost.mcp.server import build_mcp
    mcp, svc = asyncio.run(build_mcp(tmp_path / "vault"))
    # get_tools() is async and returns dict[name, Tool]
    tools = asyncio.run(mcp.get_tools())
    tool_names = set(tools.keys())
    expected = {
        "anonymize_text", "rehydrate_text", "index_path",
        "query", "vault_search", "vault_list", "vault_get",
        "daemon_status", "daemon_stop", "vault_stats",
    }
    assert expected.issubset(tool_names)
    asyncio.run(svc.close())
