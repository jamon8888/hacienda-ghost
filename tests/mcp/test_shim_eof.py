"""Stdio EOF must cause the FastMCP stdio loop to return promptly.

This is the regression test for orphan piighost serve processes that
accumulated when Claude Desktop closed pipes. If this fails, the shim
will leak processes again.
"""
from __future__ import annotations

import asyncio
import io
import sys
from unittest.mock import patch

import pytest

pytest.importorskip('fastmcp')

from piighost.mcp.shim import _build_mcp


@pytest.mark.asyncio
async def test_run_stdio_returns_within_1s_on_eof(monkeypatch) -> None:
    """Pipe an empty stream to the FastMCP stdio loop; it must return."""
    mcp = _build_mcp(base_url="http://unused", token="unused")

    # Replace stdin/stdout with empty pipes so run_stdio sees immediate EOF.
    empty_in = io.BytesIO(b"")
    discard_out = io.BytesIO()

    class _BinIO:
        def __init__(self, buf: io.BytesIO) -> None:
            self.buffer = buf

    monkeypatch.setattr(sys, "stdin", _BinIO(empty_in))
    monkeypatch.setattr(sys, "stdout", _BinIO(discard_out))

    # Should return well within 1 second on EOF.
    await asyncio.wait_for(mcp.run_stdio_async(), timeout=1.0)
