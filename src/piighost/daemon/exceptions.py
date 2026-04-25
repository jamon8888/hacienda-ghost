"""Exceptions raised by daemon discovery and lifecycle code."""
from __future__ import annotations


class DaemonDisabled(RuntimeError):
    """Raised when the user has explicitly stopped the daemon.

    Presence of ``<vault>/daemon.disabled`` means callers must NOT
    auto-spawn — they should surface a clear error telling the user to
    run ``piighost daemon start``.
    """


class DaemonStartTimeout(RuntimeError):
    """Auto-spawn timed out waiting for the handshake to appear."""
