"""Walk an InstallPlan, calling focused helpers for each step.

Importable shape: the modules used as collaborators are bound to
module-level names so tests can monkeypatch them as a single hook.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from piighost.install import clients as clients_mod
from piighost.install import models, modes
from piighost.install.plan import Client, Embedder, InstallPlan, Mode
from piighost.install.service import user_service
from piighost.install.service.user_service import UserServiceSpec
from piighost.install.ui import info, step, success


def execute(plan: InstallPlan) -> None:
    """Execute the plan. Producers (interactive / flags) build the plan;
    this function is the only place that performs side effects."""
    if plan.dry_run:
        print("piighost install — DRY RUN. Would do:")
        print(plan.describe())
        return

    _ensure_dirs(plan)

    if plan.mode is Mode.FULL:
        step("Setting up anonymizing proxy (light mode)")
        modes.run_light_mode_proxy(plan)
    elif plan.mode is Mode.STRICT:
        step("Setting up anonymizing proxy (strict mode)")
        modes.run_strict_mode_proxy(plan)
    else:
        modes.run_mcp_only(plan)

    for client in sorted(plan.clients):
        step(f"Registering MCP server in {_client_label(client)}")
        clients_mod.register(plan, client)

    if plan.install_user_service and plan.mode is not Mode.MCP_ONLY:
        if os.environ.get("PIIGHOST_SKIP_USERSVC") == "1":
            info("PIIGHOST_SKIP_USERSVC=1 — skipping user-service installation.")
        else:
            step("Installing user-level auto-restart service")
            user_service.install(_spec_for(plan))

    if plan.warmup_models:
        step("Downloading model weights")
        models.warmup(_load_service_config(plan), dry_run=False)

    _print_next_steps(plan)


def _ensure_dirs(plan: InstallPlan) -> None:
    plan.vault_dir.mkdir(parents=True, exist_ok=True)
    home = Path("~").expanduser()
    (home / ".piighost" / "logs").mkdir(parents=True, exist_ok=True)
    if plan.mode is not Mode.MCP_ONLY:
        (home / ".piighost" / "proxy").mkdir(parents=True, exist_ok=True)


def _spec_for(plan: InstallPlan) -> UserServiceSpec:
    bin_path = Path(shutil.which("piighost") or "piighost")
    log_dir = Path("~").expanduser() / ".piighost" / "logs"
    return UserServiceSpec(
        name="com.piighost.proxy",
        bin_path=bin_path,
        vault_dir=plan.vault_dir,
        log_dir=log_dir,
        listen_port=8443,
    )


def _load_service_config(plan: InstallPlan):
    from piighost.service.config import ServiceConfig
    cfg = ServiceConfig.default()
    if plan.embedder is Embedder.MISTRAL:
        cfg.embedder.backend = "mistral"
    elif plan.embedder is Embedder.NONE:
        cfg.embedder.backend = "none"
    return cfg


def _client_label(c: Client) -> str:
    return {Client.CLAUDE_CODE: "Claude Code", Client.CLAUDE_DESKTOP: "Claude Desktop"}[c]


def _print_next_steps(plan: InstallPlan) -> None:
    success("\npiighost installed.\n")
    info("Useful commands:")
    info("  piighost status          - is the proxy running?")
    info("  piighost on / off        - toggle anonymization")
    info("  piighost connect / disconnect")
    info("                           - add/remove ANTHROPIC_BASE_URL")
    info("  piighost doctor          - diagnose & self-heal")
    info("  piighost uninstall       - clean removal\n")
    info("Last-resort recovery (if 'piighost' itself is broken):")
    info("  Edit ~/.claude/settings.json and remove env.ANTHROPIC_BASE_URL.")
