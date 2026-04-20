import asyncio
import importlib.util

import pytest


@pytest.fixture()
def built_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    real_find_spec = importlib.util.find_spec

    def fake(name, *args, **kwargs):
        if name == "sentence_transformers":
            return object()
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr("importlib.util.find_spec", fake)

    from piighost.mcp.server import build_mcp
    mcp, svc = asyncio.run(build_mcp(tmp_path / "vault"))
    yield mcp, svc
    asyncio.run(svc.close())


def _payload(result):
    if hasattr(result, "structured_content") and result.structured_content:
        return result.structured_content.get("result", result.structured_content)
    return result


def test_anonymize_text_accepts_project(built_mcp):
    mcp, _ = built_mcp
    tools = asyncio.run(mcp.get_tools())
    result = asyncio.run(
        tools["anonymize_text"].run({"text": "Alice", "project": "client-a"})
    )
    payload = _payload(result)
    assert "entities" in payload


def test_list_projects_exists(built_mcp):
    mcp, _ = built_mcp
    tools = asyncio.run(mcp.get_tools())
    assert "list_projects" in tools
    assert "create_project" in tools
    assert "delete_project" in tools


def test_create_project_tool(built_mcp):
    mcp, _ = built_mcp
    tools = asyncio.run(mcp.get_tools())
    result = asyncio.run(tools["create_project"].run({"name": "client-a"}))
    payload = _payload(result)
    assert payload["name"] == "client-a"


def test_index_path_returns_project_in_response(built_mcp, tmp_path):
    mcp, _ = built_mcp
    doc_dir = tmp_path / "client-xyz" / "docs"
    doc_dir.mkdir(parents=True)
    (doc_dir / "doc.txt").write_text("Alice works in Paris")
    tools = asyncio.run(mcp.get_tools())
    result = asyncio.run(tools["index_path"].run({"path": str(doc_dir)}))
    payload = _payload(result)
    assert "project" in payload
    assert payload["project"] == "client-xyz"
