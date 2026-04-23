"""Tests for the Hacienda/Cowork MCP tools embedded in build_mcp.

These tools (resolve_project_for_folder, bootstrap_client_folder,
session_audit_append, session_audit_read) are registered as MCP tools
and tested here via the FastMCP in-process client.
"""
from __future__ import annotations

import asyncio

import pytest

fastmcp_mod = pytest.importorskip("fastmcp", reason="fastmcp extra not installed")
from fastmcp.client import Client  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    from piighost.mcp.server import build_mcp  # noqa: PLC0415

    return asyncio.run(build_mcp(tmp_path / "vault"))


async def _call(mcp, name: str, **kwargs):
    async with Client(mcp) as cli:
        result = await cli.call_tool(name, kwargs or None)
    return result.data


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def test_hacienda_tools_registered(tmp_path, monkeypatch):
    """All Hacienda cowork tools must appear in the MCP tool list."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        names = {t.name for t in asyncio.run(mcp.list_tools())}
        for expected in (
            "resolve_project_for_folder",
            "bootstrap_client_folder",
            "session_audit_append",
            "session_audit_read",
        ):
            assert expected in names, f"{expected!r} missing from MCP tool list"
    finally:
        asyncio.run(svc.close())


# ---------------------------------------------------------------------------
# resolve_project_for_folder
# ---------------------------------------------------------------------------


def test_resolve_project_deterministic(tmp_path, monkeypatch):
    """Same folder path always returns the same project slug."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        folder = str(tmp_path / "my-workspace")
        r1 = asyncio.run(_call(mcp, "resolve_project_for_folder", folder=folder))
        r2 = asyncio.run(_call(mcp, "resolve_project_for_folder", folder=folder))
        assert r1["project"] == r2["project"]
    finally:
        asyncio.run(svc.close())


def test_resolve_project_different_folders_differ(tmp_path, monkeypatch):
    """Different folders produce different project slugs."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        r_a = asyncio.run(
            _call(mcp, "resolve_project_for_folder", folder=str(tmp_path / "proj-a"))
        )
        r_b = asyncio.run(
            _call(mcp, "resolve_project_for_folder", folder=str(tmp_path / "proj-b"))
        )
        assert r_a["project"] != r_b["project"]
    finally:
        asyncio.run(svc.close())


def test_resolve_project_slug_format(tmp_path, monkeypatch):
    """Project slug is '<name>-<hash8>' — only lowercase alphanum and hyphens."""
    import re

    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        r = asyncio.run(
            _call(mcp, "resolve_project_for_folder", folder=str(tmp_path / "My Project"))
        )
        assert re.fullmatch(r"[a-z0-9\-]+", r["project"]), (
            f"slug {r['project']!r} contains invalid chars"
        )
        assert len(r["project"].split("-")[-1]) == 8, "last segment must be 8-char hash"
    finally:
        asyncio.run(svc.close())


def test_resolve_project_returns_folder(tmp_path, monkeypatch):
    """Response includes the resolved absolute folder path."""
    from pathlib import Path

    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        folder = str(tmp_path / "workspace")
        r = asyncio.run(_call(mcp, "resolve_project_for_folder", folder=folder))
        assert "folder" in r
        assert Path(r["folder"]).is_absolute()
    finally:
        asyncio.run(svc.close())


# ---------------------------------------------------------------------------
# bootstrap_client_folder
# ---------------------------------------------------------------------------


def test_bootstrap_creates_project(tmp_path, monkeypatch):
    """Bootstrap must create the project in the vault."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        folder = str(tmp_path / "workspace")
        r = asyncio.run(_call(mcp, "bootstrap_client_folder", folder=folder))
        assert r["vault_key_provisioned"] is True
        project_name = r["project"]
        projects = asyncio.run(svc.list_projects())
        assert project_name in {p.name for p in projects}
    finally:
        asyncio.run(svc.close())


def test_bootstrap_is_idempotent(tmp_path, monkeypatch):
    """Calling bootstrap twice must not create duplicate projects."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        folder = str(tmp_path / "workspace")
        r1 = asyncio.run(_call(mcp, "bootstrap_client_folder", folder=folder))
        r2 = asyncio.run(_call(mcp, "bootstrap_client_folder", folder=folder))
        assert r1["project"] == r2["project"]
        projects = asyncio.run(svc.list_projects())
        matching = [p for p in projects if p.name == r1["project"]]
        assert len(matching) == 1, "bootstrap created duplicate project entries"
    finally:
        asyncio.run(svc.close())


def test_bootstrap_project_matches_resolve(tmp_path, monkeypatch):
    """bootstrap and resolve must agree on the project slug for the same folder."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        folder = str(tmp_path / "workspace")
        boot = asyncio.run(_call(mcp, "bootstrap_client_folder", folder=folder))
        resolve = asyncio.run(_call(mcp, "resolve_project_for_folder", folder=folder))
        assert boot["project"] == resolve["project"]
    finally:
        asyncio.run(svc.close())


# ---------------------------------------------------------------------------
# session_audit_append / session_audit_read
# ---------------------------------------------------------------------------


def test_audit_read_empty_session(tmp_path, monkeypatch):
    """Reading a non-existent session returns an empty entry list."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        r = asyncio.run(_call(mcp, "session_audit_read", session_id="ghost-session"))
        assert r["count"] == 0
        assert r["entries"] == []
        assert r["session_id"] == "ghost-session"
    finally:
        asyncio.run(svc.close())


def test_audit_append_and_read(tmp_path, monkeypatch):
    """A single append is immediately visible via session_audit_read."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        asyncio.run(
            _call(
                mcp,
                "session_audit_append",
                session_id="s1",
                event="file_indexed",
                payload={"path": "/docs/contract.pdf"},
            )
        )
        r = asyncio.run(_call(mcp, "session_audit_read", session_id="s1"))
        assert r["count"] == 1
        entry = r["entries"][0]
        assert entry["event"] == "file_indexed"
        assert entry["payload"] == {"path": "/docs/contract.pdf"}
        assert "ts" in entry
    finally:
        asyncio.run(svc.close())


def test_audit_multiple_entries_ordered(tmp_path, monkeypatch):
    """Multiple appends are returned in insertion order."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        for i in range(5):
            asyncio.run(
                _call(mcp, "session_audit_append", session_id="ordered", event=f"step_{i}")
            )
        r = asyncio.run(_call(mcp, "session_audit_read", session_id="ordered"))
        assert r["count"] == 5
        assert [e["event"] for e in r["entries"]] == [f"step_{i}" for i in range(5)]
    finally:
        asyncio.run(svc.close())


def test_audit_sessions_isolated(tmp_path, monkeypatch):
    """Audit entries from session A must not appear in session B."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        asyncio.run(_call(mcp, "session_audit_append", session_id="session-a", event="alpha"))
        asyncio.run(_call(mcp, "session_audit_append", session_id="session-b", event="beta"))
        ra = asyncio.run(_call(mcp, "session_audit_read", session_id="session-a"))
        rb = asyncio.run(_call(mcp, "session_audit_read", session_id="session-b"))
        assert ra["count"] == 1 and ra["entries"][0]["event"] == "alpha"
        assert rb["count"] == 1 and rb["entries"][0]["event"] == "beta"
    finally:
        asyncio.run(svc.close())


def test_audit_append_returns_line_count(tmp_path, monkeypatch):
    """session_audit_append must return the cumulative line count."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        r1 = asyncio.run(_call(mcp, "session_audit_append", session_id="counting", event="e1"))
        assert r1["line_count"] == 1
        r2 = asyncio.run(_call(mcp, "session_audit_append", session_id="counting", event="e2"))
        assert r2["line_count"] == 2
    finally:
        asyncio.run(svc.close())


def test_audit_no_payload_defaults_to_empty_dict(tmp_path, monkeypatch):
    """Omitting payload must store {} not None."""
    mcp, svc = _make_mcp(tmp_path, monkeypatch)
    try:
        asyncio.run(
            _call(mcp, "session_audit_append", session_id="nopayload", event="ping")
        )
        r = asyncio.run(_call(mcp, "session_audit_read", session_id="nopayload"))
        assert r["entries"][0]["payload"] == {}
    finally:
        asyncio.run(svc.close())
