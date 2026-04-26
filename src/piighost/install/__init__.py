"""piighost install — typer entry point.

The interactive flow lives in `interactive.py`. The flag parser
lives in `flags.py`. Both produce an InstallPlan, which the
`executor` then walks.

`_run_light_mode` and `_run_strict_mode` are preserved as private
helpers called from `modes.py` so the existing logic for CA / leaf
cert / hosts file / service registration doesn't have to be moved.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from piighost.install import ca as ca_mod
from piighost.install import host_config, trust_store
from piighost.install.executor import execute
from piighost.install.flags import parse_flags
from piighost.install.interactive import build_plan_interactively
from piighost.install.ui import error, info, step, success, warn

# Used by Docker-flow callers; preserved for backward compatibility.
MCP_ENTRY_DOCKER = {
    "type": "sse",
    "url": "http://localhost:8080/sse",
}


def run(
    mode: Annotated[Optional[str], typer.Option(
        "--mode", help="full | mcp-only | strict (advanced) | light (deprecated)"
    )] = None,
    vault_dir: Annotated[Optional[Path], typer.Option(
        "--vault-dir", help="Where to store the PII vault and indexed docs."
    )] = None,
    embedder: Annotated[Optional[str], typer.Option(
        "--embedder", help="local | mistral | none"
    )] = None,
    mistral_api_key: Annotated[Optional[str], typer.Option(
        "--mistral-api-key", help="Required when --embedder=mistral."
    )] = None,
    clients: Annotated[Optional[str], typer.Option(
        "--clients", help="Comma-separated: code, desktop. Default: auto-detect."
    )] = None,
    user_service: Annotated[Optional[bool], typer.Option(
        "--user-service/--no-user-service",
        help="Install user-level auto-restart service (default: yes for full/strict, no for mcp-only).",
    )] = None,
    warmup: Annotated[bool, typer.Option(
        "--warmup/--no-warmup",
        help="Download model weights at install time (default: on). Set --no-warmup to defer downloads to first MCP tool call.",
    )] = True,
    force: Annotated[bool, typer.Option(
        "--force", help="Overwrite conflicting MCP entries / config."
    )] = False,
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", help="Print what would happen, don't change anything."
    )] = False,
    yes: Annotated[bool, typer.Option(
        "--yes", "-y", help="Skip the final confirmation prompt."
    )] = False,
) -> None:
    """Install piighost with the chosen mode and integrations."""
    # Backward-compat: --mode=light and --mode=strict bypass the new executor
    # and delegate directly to the legacy helpers.  These modes are deprecated
    # (light) or advanced (strict) and their helpers already contain the full
    # orchestration logic including settings.json / trust-store / hosts file.
    if mode == "light":
        print(
            "[deprecated] --mode=light is now '--mode=full'. "
            "This alias will be removed in 0.10.0."
        )
        _run_light_mode()
        return

    if mode == "strict":
        print(
            "[advanced] strict mode requires admin and modifies your "
            "hosts file. Most users want '--mode=full'. See "
            "docs/install-paths.md."
        )
        _run_strict_mode()
        return

    plan = _produce_plan(
        mode, vault_dir, embedder, mistral_api_key,
        clients, user_service, warmup, force, dry_run, yes,
    )
    execute(plan)


def _produce_plan(
    mode, vault_dir, embedder, mistral_api_key,
    clients, user_service, warmup, force, dry_run, yes,
):
    explicit_flags = any(
        v is not None for v in (mode, vault_dir, embedder, mistral_api_key, clients, user_service)
    )
    if _should_prompt(yes, dry_run, explicit_flags):
        plan = build_plan_interactively(starting_defaults=None)
        return plan

    try:
        result = parse_flags(
            mode=mode,
            vault_dir=vault_dir,
            embedder=embedder,
            mistral_api_key=mistral_api_key,
            clients=clients,
            user_service=user_service,
            warmup=warmup,
            force=force,
            dry_run=dry_run,
            yes=yes,
            env=dict(os.environ),
        )
    except ValueError as exc:
        error(str(exc))
        raise typer.Exit(code=1)

    for d in result.deprecations:
        # Print the full message verbatim (rich would strip [deprecated]/[advanced]
        # markup tags, so bypass warn() for deprecation notices).
        print(d.message)
    return result.plan


def _should_prompt(yes: bool, dry_run: bool, explicit_flags: bool) -> bool:
    if yes or dry_run or explicit_flags:
        return False
    return sys.stdin.isatty()


# ---- legacy private helpers preserved for modes.py ----------------------

def _run_light_mode() -> None:
    """Phase 1 light-mode orchestration: CA generation + OS trust store + Claude Code settings."""
    step("Generating local root CA and leaf certificate")
    vault = Path(os.path.expanduser("~")) / ".piighost"
    proxy_dir = vault / "proxy"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    root = ca_mod.generate_root(common_name="piighost local CA")
    leaf = ca_mod.generate_leaf(root, hostnames=["localhost", "127.0.0.1"])
    (proxy_dir / "ca.pem").write_bytes(root.cert_pem)
    (proxy_dir / "ca.key").write_bytes(root.key_pem)
    (proxy_dir / "leaf.pem").write_bytes(leaf.cert_pem)
    (proxy_dir / "leaf.key").write_bytes(leaf.key_pem)
    success("CA and leaf cert written to ~/.piighost/proxy/")

    step("Installing CA into OS trust store")
    if os.environ.get("PIIGHOST_SKIP_TRUSTSTORE") == "1":
        info("PIIGHOST_SKIP_TRUSTSTORE=1 — skipping trust store installation.")
    else:
        try:
            trust_store.install_ca(proxy_dir / "ca.pem")
            success("CA installed in OS trust store.")
        except Exception as exc:
            warn(f"Trust store install failed: {exc} — install manually.")

    step("Configuring Claude Code (ANTHROPIC_BASE_URL)")
    settings_path = Path(os.path.expanduser("~")) / ".claude" / "settings.json"
    host_config.set_claude_code_base_url(settings_path, "https://localhost:8443")
    success(f"ANTHROPIC_BASE_URL written to {settings_path}")

    success("\nLight mode installed. Start the proxy with: piighost proxy run")


def _run_strict_mode() -> None:
    """Phase 2 strict-mode: CA for api.anthropic.com + hosts file +
    sudo background service on :443. Reachable only via --mode=strict."""
    import shutil
    vault = Path(os.path.expanduser("~")) / ".piighost"
    proxy_dir = vault / "proxy"
    proxy_dir.mkdir(parents=True, exist_ok=True)

    step("Generating local root CA and leaf certificate for api.anthropic.com")
    root = ca_mod.generate_root(common_name="piighost local CA")
    leaf = ca_mod.generate_leaf(root, hostnames=["api.anthropic.com"])
    (proxy_dir / "ca.pem").write_bytes(root.cert_pem)
    (proxy_dir / "ca.key").write_bytes(root.key_pem)
    (proxy_dir / "leaf.pem").write_bytes(leaf.cert_pem)
    (proxy_dir / "leaf.key").write_bytes(leaf.key_pem)
    success("CA and leaf cert written to ~/.piighost/proxy/")

    step("Installing CA into OS trust store")
    if os.environ.get("PIIGHOST_SKIP_TRUSTSTORE") == "1":
        info("PIIGHOST_SKIP_TRUSTSTORE=1 — skipping trust store installation.")
    else:
        try:
            trust_store.install_ca(proxy_dir / "ca.pem")
            success("CA installed in OS trust store.")
        except Exception as exc:
            warn(f"Trust store install failed: {exc} — install manually.")

    step("Editing hosts file (127.0.0.1 api.anthropic.com)")
    from piighost.install import hosts_file as hf
    try:
        hf.add_redirect("api.anthropic.com")
        success("Hosts file updated.")
    except Exception as exc:
        warn(f"Hosts file edit failed: {exc}")

    step("Installing background service (port 443)")
    if os.environ.get("PIIGHOST_SKIP_SERVICE") == "1":
        info("PIIGHOST_SKIP_SERVICE=1 — skipping service installation.")
    else:
        from piighost.install import service as svc
        bin_path = shutil.which("piighost")
        if bin_path is None:
            warn(
                "piighost binary not found on PATH. "
                "Service registration requires piighost to be installed as a command. "
                "Run: pip install piighost[proxy]"
            )
            warn("Skipping service installation.")
        else:
            spec = svc.ServiceSpec(
                name="com.piighost.proxy",
                bin_path=bin_path,
                vault_dir=vault,
                cert_path=proxy_dir / "leaf.pem",
                key_path=proxy_dir / "leaf.key",
                port=443,
            )
            try:
                svc.install_service(spec)
                success("Background service installed and started.")
            except Exception as exc:
                warn(f"Service install failed: {exc}")

    success("\nStrict mode installed. Verify with: piighost doctor")
