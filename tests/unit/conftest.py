"""Shared fixtures and environment setup for CLI + service unit tests.

Does two things at import time:

1. Force ``COLUMNS=200`` so Typer's Rich-rendered ``--help`` text does
   not wrap long option names (``--project``, ``--filter-prefix``, …)
   off-screen on 80-col CI runners.

2. Skip collection of the MCP-server unit tests when the optional
   ``fastmcp`` extra is not installed. Those test files import
   ``piighost.mcp.server.build_mcp`` which in turn does
   ``from fastmcp import FastMCP`` at module top; without the extras,
   collection itself fails with ``ModuleNotFoundError: fastmcp``.
"""
from __future__ import annotations

import os
from importlib.util import find_spec

os.environ.setdefault("COLUMNS", "200")
# Disable any smart terminal heuristics that might re-detect width.
os.environ.setdefault("TERM", "dumb")

# Gate MCP tests behind the ``fastmcp`` optional dep so slim CI envs
# (default ``uv sync --dev``) still collect cleanly.
if find_spec("fastmcp") is None:
    collect_ignore_glob = ["test_mcp_*.py"]
