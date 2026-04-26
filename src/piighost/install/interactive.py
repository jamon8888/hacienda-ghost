"""Interactive prompts for `piighost install` when stdin is a TTY.

Uses a single `_ask` indirection so tests can swap the input source
for a scripted iterator.
"""
from __future__ import annotations

import os
from pathlib import Path

from piighost.install.clients import detect_all
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


def _ask(prompt: str, *, default: str = "") -> str:
    """Default input source. Tests monkeypatch this."""
    full = f"{prompt} " + (f"[{default}] " if default else "")
    raw = input(full).strip()
    return raw or default


def build_plan_interactively(starting_defaults: InstallPlan | None) -> InstallPlan:
    """Walk the user through 4 prompts + final review. Raise SystemExit
    if the user declines at the review."""
    print()
    print("┌─ piighost install ───────────────────────────────────────")
    print("│")
    mode = _prompt_mode()
    clients = _prompt_clients()
    vault_dir = _prompt_vault_dir()
    embedder, mistral_key = _prompt_embedder()

    install_user_service = mode is not Mode.MCP_ONLY

    plan = InstallPlan(
        mode=mode,
        vault_dir=vault_dir,
        embedder=embedder,
        mistral_api_key=mistral_key,
        clients=clients,
        install_user_service=install_user_service,
        warmup_models=True,  # default-on so the first MCP tool call doesn't pay the 45s download cost
        force=False,
        dry_run=False,
    )

    print()
    print("Review:")
    print(plan.describe())
    print()
    answer = _ask("Proceed? [Y/n]", default="y").lower()
    if answer not in ("y", "yes"):
        print("Aborted.")
        raise SystemExit(1)

    return plan


def _prompt_mode() -> Mode:
    print("│ 1. Mode")
    print("│    1) Full      Anonymizing proxy + MCP tools + RAG")
    print("│    2) MCP-only  MCP tools + RAG. No proxy.")
    raw = _ask("│  Choose:", default="1")
    if raw in ("1", "full"):
        return Mode.FULL
    if raw in ("2", "mcp-only"):
        return Mode.MCP_ONLY
    print(f"│  Unknown choice {raw!r}, defaulting to Full.")
    return Mode.FULL


def _prompt_clients() -> frozenset[Client]:
    detected = {loc.client: loc.exists for loc in detect_all()}
    print("│")
    print("│ 2. Register MCP server in (csv: 1=Code, 2=Desktop, blank=none):")
    for i, client in enumerate([Client.CLAUDE_CODE, Client.CLAUDE_DESKTOP], start=1):
        marker = "✓" if detected.get(client) else " "
        print(f"│    {i}) [{marker}] {_label(client)}")
    raw = _ask("│  Choose:", default=_default_client_csv(detected))
    if not raw.strip():
        return frozenset()
    out: set[Client] = set()
    mapping = {"1": Client.CLAUDE_CODE, "2": Client.CLAUDE_DESKTOP}
    for tok in raw.split(","):
        tok = tok.strip()
        if tok in mapping:
            out.add(mapping[tok])
    return frozenset(out)


def _prompt_vault_dir() -> Path:
    default = Path.home() / ".piighost" / "vault"
    print("│")
    raw = _ask("│ 3. Vault directory", default=str(default))
    return Path(raw).expanduser()


def _prompt_embedder() -> tuple[Embedder, str | None]:
    print("│")
    print("│ 4. Embedder backend")
    print("│    1) Local    ~500 MB download, runs offline")
    print("│    2) Mistral  Remote API, needs MISTRAL_API_KEY")
    print("│    3) None     Skip RAG embedding (anonymize-only)")
    raw = _ask("│  Choose:", default="1")
    if raw in ("2", "mistral"):
        key = (
            os.environ.get("MISTRAL_API_KEY")
            or _ask("│  MISTRAL_API_KEY:", default="")
            or None
        )
        if not key:
            print("│  No API key supplied; falling back to local embedder.")
            return Embedder.LOCAL, None
        return Embedder.MISTRAL, key
    if raw in ("3", "none"):
        return Embedder.NONE, None
    return Embedder.LOCAL, None


def _default_client_csv(detected: dict[Client, bool]) -> str:
    csv: list[str] = []
    if detected.get(Client.CLAUDE_CODE):
        csv.append("1")
    if detected.get(Client.CLAUDE_DESKTOP):
        csv.append("2")
    return ",".join(csv)


def _label(c: Client) -> str:
    return {Client.CLAUDE_CODE: "Claude Code", Client.CLAUDE_DESKTOP: "Claude Desktop"}[c]
