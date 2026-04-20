import asyncio
import importlib.util
import pytest


@pytest.fixture()
def built_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")

    real_find_spec = importlib.util.find_spec

    def fake_find_spec_available(name, *args, **kwargs):
        if name == "sentence_transformers":
            return object()
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec_available)

    from piighost.mcp.server import build_mcp

    vault_dir = tmp_path / "vault"
    mcp, svc = asyncio.run(build_mcp(vault_dir))
    yield mcp, svc
    asyncio.run(svc.close())


def test_indexing_tools_registered_when_available(built_mcp):
    mcp, _ = built_mcp
    tools = asyncio.run(mcp.get_tools())
    assert "index_path" in tools
    assert "query" in tools


def test_indexing_tools_not_registered_when_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")

    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "sentence_transformers":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)

    from piighost.mcp.server import build_mcp

    vault_dir = tmp_path / "vault"
    mcp, svc = asyncio.run(build_mcp(vault_dir))
    try:
        tools = asyncio.run(mcp.get_tools())
        assert "index_path" not in tools
        assert "query" not in tools
        assert "anonymize_text" in tools
        assert "rehydrate_text" in tools
        assert "vault_list" in tools
    finally:
        asyncio.run(svc.close())
