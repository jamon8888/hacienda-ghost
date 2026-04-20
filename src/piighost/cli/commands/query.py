"""`piighost query <text>` — hybrid BM25+vector search."""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from piighost.cli.commands.vault import _load_cfg, _resolve_vault
from piighost.cli.output import ExitCode, emit_error_line, emit_json_line
from piighost.daemon.client import DaemonClient
from piighost.exceptions import VaultNotFound
from piighost.indexer.filters import QueryFilter
from piighost.service import PIIGhostService


def run(
    text: str = typer.Argument(..., help="Query text"),
    vault: Path | None = typer.Option(None, "--vault"),
    k: int = typer.Option(5, "--k", "-k"),
    project: str = typer.Option("default", "--project", help="Project name (defaults to 'default')"),
    filter_prefix: str = typer.Option(
        "",
        "--filter-prefix",
        help="Restrict search to file_path starting with this prefix",
    ),
    filter_doc_ids: str = typer.Option(
        "",
        "--filter-doc-ids",
        help="Comma-separated doc_ids to restrict search to",
    ),
    rerank: bool = typer.Option(
        False,
        "--rerank/--no-rerank",
        help="Apply cross-encoder reranking",
    ),
    top_n: int = typer.Option(
        20,
        "--top-n",
        help="Candidate pool size before reranking",
    ),
) -> None:
    try:
        vault_dir = _resolve_vault(vault)
    except VaultNotFound as exc:
        emit_error_line(
            error="VaultNotFound",
            message=str(exc),
            hint="Run `piighost init`",
            exit_code=ExitCode.USER_ERROR,
        )
        raise typer.Exit(code=int(ExitCode.USER_ERROR))

    filter_params: dict = {}
    if filter_prefix:
        filter_params["file_path_prefix"] = filter_prefix
    if filter_doc_ids:
        doc_ids = [d.strip() for d in filter_doc_ids.split(",") if d.strip()]
        if doc_ids:
            filter_params["doc_ids"] = doc_ids

    client = DaemonClient.from_vault(vault_dir)
    if client is not None:
        payload = {
            "text": text,
            "k": k,
            "project": project,
            "filter": filter_params or None,
            "rerank": rerank,
            "top_n": top_n,
        }
        result = client.call("query", payload)
        emit_json_line(result)
        return

    asyncio.run(
        _query(
            vault_dir,
            text,
            k,
            project,
            filter_params=filter_params,
            rerank=rerank,
            top_n=top_n,
        )
    )


async def _query(
    vault_dir: Path,
    text: str,
    k: int,
    project: str = "default",
    *,
    filter_params: dict | None = None,
    rerank: bool = False,
    top_n: int = 20,
) -> None:
    config = _load_cfg(vault_dir)
    svc = await PIIGhostService.create(vault_dir=vault_dir, config=config)
    try:
        qfilter: QueryFilter | None = None
        if filter_params:
            qfilter = QueryFilter(
                file_path_prefix=filter_params.get("file_path_prefix"),
                doc_ids=tuple(filter_params.get("doc_ids", [])),
            )
        result = await svc.query(
            text,
            k=k,
            project=project,
            filter=qfilter,
            rerank=rerank,
            top_n=top_n,
        )
        emit_json_line(result.model_dump())
    finally:
        await svc.close()
