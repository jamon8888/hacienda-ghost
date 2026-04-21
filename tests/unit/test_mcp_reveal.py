import asyncio
import pytest


@pytest.fixture()
def mcp_with_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    from piighost.mcp.server import build_mcp

    vault_dir = tmp_path / "vault"
    mcp, svc = asyncio.run(build_mcp(vault_dir))
    # Seed the vault with one entity via anonymize
    asyncio.run(svc.anonymize("Alice lives in Paris"))
    yield mcp, svc
    asyncio.run(svc.close())


def _tools_by_name(mcp):
    """Build a name→Tool dict. FastMCP 3.x replaced get_tools() with list_tools()."""
    tools = asyncio.run(mcp.list_tools())
    return {t.name: t for t in tools}


def test_vault_list_reveal_false_masks_original(mcp_with_vault):
    mcp, _ = mcp_with_vault
    tools = _tools_by_name(mcp)
    vault_list_tool = tools["vault_list"]
    result = asyncio.run(vault_list_tool.run({"reveal": False}))
    entries = result.structured_content["result"]
    assert len(entries) > 0, "vault must contain at least one entry after anonymize"
    for e in entries:
        assert e.get("original") is None, (
            f"reveal=False must not expose original; got {e}"
        )


def test_vault_list_reveal_true_surfaces_original(mcp_with_vault):
    mcp, _ = mcp_with_vault
    tools = _tools_by_name(mcp)
    vault_list_tool = tools["vault_list"]
    result = asyncio.run(vault_list_tool.run({"reveal": True}))
    entries = result.structured_content["result"]
    assert len(entries) > 0, "vault must contain at least one entry after anonymize"
    has_original = any(e.get("original") is not None for e in entries)
    assert has_original, "reveal=True should populate at least one original field"
