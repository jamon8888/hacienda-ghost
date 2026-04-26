"""Detect installed Claude clients and register the MCP server.

Stub for Task 2 import-time satisfaction. Real implementation in Task 3.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from piighost.install.plan import Client


@dataclass(frozen=True)
class ClientLocation:
    client: Client
    config_path: Path
    exists: bool


def detect_all() -> list[ClientLocation]:
    return []
