"""`piighost rehydrate` — reverse anonymized text via vault."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer

from piighost.cli.io_utils import read_input
from piighost.cli.output import ExitCode, emit_error_line, emit_json_line
from piighost.exceptions import PIISafetyViolation, VaultNotFound
from piighost.vault.discovery import find_vault_dir


def run(
    target: str = typer.Argument(..., help="File path or '-' for stdin"),
    vault: Path | None = typer.Option(None, "--vault"),
    lenient: bool = typer.Option(False, "--lenient"),
) -> None:
    try:
        vault_dir = find_vault_dir(
            start=Path(os.environ.get("PIIGHOST_CWD", Path.cwd())),
            explicit=vault,
        )
    except VaultNotFound as exc:
        emit_error_line(
            error="VaultNotFound",
            message=str(exc),
            hint="Run `piighost init` or pass --vault",
            exit_code=ExitCode.USER_ERROR,
        )
        raise typer.Exit(code=int(ExitCode.USER_ERROR))

    _, text = read_input(target)
    try:
        asyncio.run(_run(vault_dir, text, strict=not lenient))
    except PIISafetyViolation as exc:
        emit_error_line(
            error="PIISafetyViolation",
            message=str(exc),
            hint="Pass --lenient to skip unknown tokens",
            exit_code=ExitCode.PII_SAFETY_VIOLATION,
        )
        raise typer.Exit(code=int(ExitCode.PII_SAFETY_VIOLATION))


async def _run(vault_dir: Path, text: str, *, strict: bool) -> None:
    from piighost.service import PIIGhostService, ServiceConfig

    cfg_path = vault_dir / "config.toml"
    config = (
        ServiceConfig.from_toml(cfg_path) if cfg_path.exists() else ServiceConfig.default()
    )
    svc = await PIIGhostService.create(vault_dir=vault_dir, config=config)
    try:
        result = await svc.rehydrate(text, strict=strict)
        emit_json_line(result.model_dump())
    finally:
        await svc.close()
