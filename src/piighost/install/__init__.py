from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from piighost.install import claude_config, docker, models, preflight, uv_path
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
) -> None:
    """Install piighost with all models and register it in Claude Desktop."""
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


def _load_config() -> ServiceConfig:
    config_path = Path(".piighost") / "config.toml"
    if config_path.exists():
        return ServiceConfig.from_toml(config_path)
    return ServiceConfig.default()
