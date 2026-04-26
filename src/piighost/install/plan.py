"""InstallPlan dataclass + supporting StrEnums.

The plan is a pure-data record of what `piighost install` will do.
Both the interactive prompts (`interactive.py`) and the CLI flag
parser (`flags.py`) produce one; the executor (`executor.py`) reads
one and walks it linearly.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Mode(StrEnum):
    """Top-level install mode.

    `--mode=light` is NOT a value here. It is mapped to `FULL` by
    `flags.py` after printing a deprecation warning.
    """

    FULL = "full"           # light proxy + MCP + RAG (interactive default)
    MCP_ONLY = "mcp-only"   # MCP + RAG, no proxy
    STRICT = "strict"       # legacy: system-wide proxy (not in menu)


class Embedder(StrEnum):
    LOCAL = "local"      # ~500 MB sentence-transformers download
    MISTRAL = "mistral"  # remote API, needs MISTRAL_API_KEY
    NONE = "none"        # skip RAG embedding


class Client(StrEnum):
    CLAUDE_CODE = "code"
    CLAUDE_DESKTOP = "desktop"


@dataclass(frozen=True)
class InstallPlan:
    """Frozen description of an install run.

    Validation runs in `__post_init__`; bad combinations raise
    `ValueError` so producers can surface clear messages.
    """

    mode: Mode
    vault_dir: Path
    embedder: Embedder
    mistral_api_key: str | None
    clients: frozenset[Client]
    install_user_service: bool
    warmup_models: bool
    force: bool
    dry_run: bool

    def __post_init__(self) -> None:
        if self.embedder is Embedder.MISTRAL and not self.mistral_api_key:
            raise ValueError(
                "embedder=mistral requires mistral_api_key (pass --mistral-api-key "
                "or set the MISTRAL_API_KEY env var)."
            )
        if self.mode is Mode.MCP_ONLY and self.install_user_service:
            raise ValueError(
                "install_user_service has no effect in mcp-only mode "
                "(no proxy daemon to restart)."
            )
        if self.mode is Mode.STRICT and not self.install_user_service:
            raise ValueError(
                "strict mode needs the auto-restart service "
                "(remove --no-user-service or pick a different mode)."
            )

    def describe(self) -> str:
        """Bullet-list rendering for --dry-run and the closing review."""
        lines: list[str] = []
        if self.mode in (Mode.FULL, Mode.STRICT):
            lines.append("  • Generate CA + leaf cert at ~/.piighost/proxy/")
        if self.mode is Mode.STRICT:
            lines.append("  • Add 127.0.0.1 api.anthropic.com to hosts file (sudo)")
            lines.append("  • Install system-level background service on :443 (sudo)")
        if self.clients:
            client_names = ", ".join(self._client_label(c) for c in sorted(self.clients))
            lines.append(f"  • Register MCP server in {client_names}")
        if self.mode is Mode.FULL and Client.CLAUDE_CODE in self.clients:
            lines.append("  • Set ANTHROPIC_BASE_URL=https://localhost:8443 for Claude Code")
        if self.install_user_service:
            lines.append("  • Install user-level auto-restart service")
        lines.append(f"  • Vault: {self.vault_dir.as_posix()}")
        if self.embedder is Embedder.NONE:
            lines.append(
                "  • Embedder: none (RAG indexing/query disabled until you "
                "run `piighost config set embedder ...`)"
            )
        else:
            embedder_note = {
                Embedder.LOCAL: "local (~500 MB download)",
                Embedder.MISTRAL: "Mistral API",
            }[self.embedder]
            lines.append(f"  • Embedder: {embedder_note}")
        if self.warmup_models:
            lines.append("  • Download model weights now")
        return "\n".join(lines)

    @staticmethod
    def _client_label(c: Client) -> str:
        return {Client.CLAUDE_CODE: "Claude Code", Client.CLAUDE_DESKTOP: "Claude Desktop"}[c]
