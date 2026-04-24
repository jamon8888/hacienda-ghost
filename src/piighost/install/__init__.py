from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from piighost.install import ca as ca_mod
from piighost.install import claude_config, docker, host_config, models, preflight, trust_store, uv_path
from piighost.install.ui import error, info, step, success, warn
from piighost.service.config import ServiceConfig

MCP_ENTRY_UV = {
    "type": "stdio",
    "command": "uvx",
    "args": [
        "--from", "piighost[mcp,index,gliner2]",
        "piighost", "serve", "--transport", "stdio",
    ],
    "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
}

MCP_ENTRY_DOCKER = {
    "type": "sse",
    "url": "http://localhost:8080/sse",
}


def run(
    full: Annotated[bool, typer.Option("--full", help="Download all models")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print actions without executing")] = False,
    no_docker: Annotated[bool, typer.Option("--no-docker", help="Force uv path")] = False,
    reranker: Annotated[bool, typer.Option("--reranker", help="Also warm up reranker")] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing config; ignore disk warning")] = False,
    mode: Annotated[str, typer.Option("--mode", help="Install mode: 'light' (CA + proxy, no Docker) or 'strict' (Phase 2)")] = "light",
) -> None:
    """Install piighost with all models and register it in Claude Desktop."""
    # Phase 1: light mode — generate CA, write settings.json. Skip heavy install steps.
    if mode == "strict":
        typer.echo("--mode=strict is not yet implemented (Phase 2).")
        raise typer.Exit(code=2)

    if mode == "light":
        _run_light_mode()
        return

    if dry_run:
        info("Dry run — no changes will be made.")

    # Step 1: Pre-flight
    step("Pre-flight checks")
    try:
        preflight.check_python_version()
        try:
            preflight.check_disk_space(min_gb=2.0)
        except preflight.PreflightError as exc:
            if not force:
                error(str(exc))
                raise typer.Exit(code=1)
            warn(f"{exc} — continuing because --force was passed.")
        preflight.check_internet()
    except preflight.PreflightError as exc:
        error(str(exc))
        raise typer.Exit(code=1)
    success("Pre-flight checks passed.")

    # Step 2: Docker detection
    use_docker = False
    if not no_docker:
        step("Detecting Docker")
        use_docker = docker.docker_available()
        if use_docker:
            info("Docker daemon is running — using Docker path.")
        else:
            info("Docker not available — using uv path.")

    # Step 3: Install backend
    if use_docker:
        step("Pulling and starting Docker services")
        try:
            docker.compose_pull_and_up(dry_run=dry_run)
        except docker.DockerError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        success("Docker services running.")
    else:
        step("Installing piighost via uv")
        try:
            uv_bin = uv_path.ensure_uv()
        except uv_path.UvNotFoundError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        try:
            uv_path.install_piighost(uv_path=uv_bin, dry_run=dry_run)
        except RuntimeError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        success("piighost installed.")

    # Step 4: Model warm-up
    if full:
        cfg = _load_config()
        step("Warming up NER model (GLiNER2 + French adapter)")
        try:
            models.warmup_ner(cfg, dry_run=dry_run)
        except models.WarmupError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        success("NER model ready.")

        step("Warming up embedder model (Solon)")
        try:
            models.warmup_embedder(cfg, dry_run=dry_run)
        except models.WarmupError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        success("Embedder model ready.")

        if reranker:
            step("Warming up reranker model (BGE)")
            try:
                models.warmup_reranker(cfg, dry_run=dry_run)
            except models.WarmupError as exc:
                error(str(exc))
                raise typer.Exit(code=1)
            success("Reranker model ready.")

    # Step 5: Claude Desktop config
    step("Registering MCP server in Claude Desktop")
    mcp_entry = MCP_ENTRY_DOCKER if use_docker else MCP_ENTRY_UV
    config_path = claude_config.find_claude_config()
    if config_path is None:
        warn("Claude Desktop config not found. Add this to claude_desktop_config.json manually:")
        info(json.dumps({"mcpServers": {"piighost": mcp_entry}}, indent=2))
    else:
        try:
            claude_config.backup_config(config_path)
            claude_config.merge_mcp_entry(config_path, "piighost", mcp_entry, force=force)
            success(f"Registered in {config_path}")
        except claude_config.AlreadyRegisteredError as exc:
            warn(str(exc))
        except claude_config.MalformedConfigError as exc:
            warn(str(exc))

    # Done
    success("\npiighost is ready. Restart Claude Desktop to activate the MCP server.")


def _run_light_mode() -> None:
    """Phase 1 light-mode orchestration: CA generation + OS trust store + Claude Code settings."""
    # Step: Generate CA and leaf cert
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

    # Step: Install CA into OS trust store
    step("Installing CA into OS trust store")
    if os.environ.get("PIIGHOST_SKIP_TRUSTSTORE") == "1":
        info("PIIGHOST_SKIP_TRUSTSTORE=1 — skipping trust store installation.")
    else:
        try:
            trust_store.install_ca(proxy_dir / "ca.pem")
            success("CA installed in OS trust store.")
        except Exception as exc:
            warn(f"Trust store install failed: {exc} — install manually.")

    # Step: Configure Claude Code base URL
    step("Configuring Claude Code (ANTHROPIC_BASE_URL)")
    settings_path = Path(os.path.expanduser("~")) / ".claude" / "settings.json"
    host_config.set_claude_code_base_url(settings_path, "https://localhost:8443")
    success(f"ANTHROPIC_BASE_URL written to {settings_path}")

    success("\nLight mode installed. Start the proxy with: piighost proxy run")


def _load_config() -> ServiceConfig:
    config_path = Path(".piighost") / "config.toml"
    if config_path.exists():
        return ServiceConfig.from_toml(config_path)
    return ServiceConfig.default()
