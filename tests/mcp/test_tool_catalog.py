"""MCP tool catalog covers every daemon RPC method."""
from __future__ import annotations

from piighost.mcp.tools import TOOL_CATALOG, ToolSpec


def test_catalog_is_nonempty() -> None:
    assert len(TOOL_CATALOG) >= 14


def test_every_tool_has_required_fields() -> None:
    for spec in TOOL_CATALOG:
        assert isinstance(spec, ToolSpec)
        assert spec.name and spec.name.replace("_", "").isalnum()
        assert spec.rpc_method
        assert spec.description
        assert spec.timeout_s > 0


def test_tool_names_unique() -> None:
    names = [s.name for s in TOOL_CATALOG]
    assert len(names) == len(set(names))


def test_index_path_has_long_timeout() -> None:
    by_name = {s.name: s for s in TOOL_CATALOG}
    assert by_name["index_path"].timeout_s >= 600


def test_vault_stats_has_short_timeout() -> None:
    by_name = {s.name: s for s in TOOL_CATALOG}
    assert by_name["vault_stats"].timeout_s <= 5


def test_anonymize_text_maps_to_anonymize_rpc() -> None:
    by_name = {s.name: s for s in TOOL_CATALOG}
    assert by_name["anonymize_text"].rpc_method == "anonymize"


def test_rehydrate_text_maps_to_rehydrate_rpc() -> None:
    by_name = {s.name: s for s in TOOL_CATALOG}
    assert by_name["rehydrate_text"].rpc_method == "rehydrate"
