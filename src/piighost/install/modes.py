"""Thin wrappers around the existing _run_light_mode / _run_strict_mode
runners in install/__init__.py, plus a no-op MCP-only runner.

Kept as a separate module so the executor can import it without
forming an import cycle through __init__.
"""
from __future__ import annotations

from piighost.install.plan import InstallPlan


def run_light_mode_proxy(plan: InstallPlan) -> None:
    """CA + leaf cert at <vault>/proxy/. No system changes."""
    from piighost.install import _run_light_mode
    _run_light_mode()  # signature stays env-driven for now


def run_strict_mode_proxy(plan: InstallPlan) -> None:
    """CA for api.anthropic.com + hosts file + sudo service.
    Reachable only via --mode=strict (deprecated)."""
    from piighost.install import _run_strict_mode
    _run_strict_mode()


def run_mcp_only(plan: InstallPlan) -> None:
    """No-op. RAG/extraction work is provided by the installed extras
    at MCP server startup. This runner exists for symmetry and as a
    natural place to add MCP-only-specific setup steps later."""
    return
