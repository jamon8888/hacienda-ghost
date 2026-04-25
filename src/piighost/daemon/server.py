"""Starlette app exposing PIIGhostService over JSON-RPC at /rpc.

Loopback-only. Bearer-token auth via Authorization header.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from piighost.daemon import reaper
from piighost.daemon.audit_log import emit
from piighost.service import PIIGhostService
from piighost.service.config import ServiceConfig


def _make_lifespan(vault_dir: Path, base_lifespan):
    """Build a Starlette lifespan that wraps *base_lifespan* and runs the
    reaper every 60s.

    Lifecycle events (daemon_started, reaper_killed, daemon_stopped) are
    appended to <vault>/daemon.log as JSON lines.
    """
    log_path = vault_dir / "daemon.log"

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        emit(log_path, "daemon_started", port=getattr(app.state, "port", None))

        async def _reaper_loop() -> None:
            while True:
                try:
                    killed = reaper.reap()
                    if killed:
                        emit(log_path, "reaper_killed", reaped_pids=killed)
                except Exception as exc:  # pragma: no cover
                    emit(log_path, "reaper_error", error=str(exc))
                await asyncio.sleep(60)

        task = asyncio.create_task(_reaper_loop())
        try:
            async with base_lifespan(app):
                yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            emit(log_path, "daemon_stopped")

    return lifespan


def build_app(vault_dir: Path) -> tuple[Starlette, str]:
    token = secrets.token_urlsafe(32)
    cfg_path = vault_dir / "config.toml"
    config = (
        ServiceConfig.from_toml(cfg_path) if cfg_path.exists() else ServiceConfig.default()
    )

    state: dict[str, Any] = {"service": None}
    shutdown_event = asyncio.Event()

    @asynccontextmanager
    async def _base_lifespan(_: Starlette) -> AsyncIterator[None]:
        state["service"] = await PIIGhostService.create(
            vault_dir=vault_dir, config=config
        )
        try:
            yield
        finally:
            svc: PIIGhostService | None = state["service"]
            if svc:
                await svc.close()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def rpc(request: Request) -> JSONResponse:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        method = body.get("method")
        params = body.get("params", {}) or {}
        svc: PIIGhostService = state["service"]
        try:
            result = await _dispatch(svc, method, params)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {"code": -32000, "message": type(exc).__name__},
                }
            )
        return JSONResponse(
            {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
        )

    async def shutdown(request: Request) -> JSONResponse:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        shutdown_event.set()
        return JSONResponse({"ok": True})

    routes = [
        Route("/health", health),
        Route("/rpc", rpc, methods=["POST"]),
        Route("/shutdown", shutdown, methods=["POST"]),
    ]
    app = Starlette(routes=routes, lifespan=_make_lifespan(vault_dir, _base_lifespan))
    app.state.shutdown_event = shutdown_event
    return app, token


async def _dispatch(
    svc: PIIGhostService, method: str, params: dict[str, Any]
) -> Any:
    if method == "anonymize":
        r = await svc.anonymize(
            params["text"],
            doc_id=params.get("doc_id"),
            project=params.get("project", "default"),
        )
        return r.model_dump()
    if method == "rehydrate":
        r = await svc.rehydrate(
            params["text"],
            strict=params.get("strict"),
            project=params.get("project", "default"),
        )
        return r.model_dump()
    if method == "detect":
        return [
            d.model_dump()
            for d in await svc.detect(
                params["text"],
                project=params.get("project", "default"),
            )
        ]
    if method == "vault_list":
        r = await svc.vault_list(
            label=params.get("label"),
            limit=params.get("limit", 100),
            reveal=params.get("reveal", False),
            project=params.get("project", "default"),
        )
        return r.model_dump()
    if method == "vault_show":
        r = await svc.vault_show(
            params["token"],
            reveal=params.get("reveal", False),
            project=params.get("project", "default"),
        )
        return r.model_dump() if r else None
    if method == "vault_stats":
        return (
            await svc.vault_stats(project=params.get("project", "default"))
        ).model_dump()
    if method == "vault_search":
        entries = await svc.vault_search(
            params["query"],
            reveal=params.get("reveal", False),
            limit=params.get("limit", 100),
            project=params.get("project", "default"),
        )
        return [e.model_dump() for e in entries]
    if method == "index_path":
        from pathlib import Path as _Path

        raw_project = params.get("project", "")
        project = raw_project if raw_project else None
        report = await svc.index_path(
            _Path(params["path"]),
            recursive=params.get("recursive", True),
            force=params.get("force", False),
            project=project,
        )
        return report.model_dump()
    if method == "remove_doc":
        removed = await svc.remove_doc(
            Path(params["path"]),
            project=params.get("project", "default"),
        )
        return {"removed": removed}
    if method == "index_status":
        status = await svc.index_status(
            limit=params.get("limit", 100),
            offset=params.get("offset", 0),
            project=params.get("project", "default"),
        )
        return status.model_dump()
    if method == "query":
        from piighost.indexer.filters import QueryFilter

        raw_filter = params.get("filter")
        qfilter = None
        if raw_filter:
            qfilter = QueryFilter(
                file_path_prefix=raw_filter.get("file_path_prefix") or None,
                doc_ids=tuple(raw_filter.get("doc_ids") or ()),
            )
        result = await svc.query(
            params["text"],
            k=params.get("k", 5),
            project=params.get("project", "default"),
            filter=qfilter,
            rerank=params.get("rerank", False),
            top_n=params.get("top_n", 20),
        )
        return result.model_dump()
    if method == "list_projects":
        projects = await svc.list_projects()
        return [
            {
                "name": p.name,
                "description": p.description,
                "created_at": p.created_at,
                "last_accessed_at": p.last_accessed_at,
                "placeholder_salt": p.placeholder_salt,
            }
            for p in projects
        ]
    if method == "create_project":
        info = await svc.create_project(
            params["name"],
            description=params.get("description", ""),
        )
        return {
            "name": info.name,
            "description": info.description,
            "created_at": info.created_at,
        }
    if method == "delete_project":
        deleted = await svc.delete_project(
            params["name"], force=params.get("force", False)
        )
        return {"deleted": deleted, "name": params["name"]}
    raise ValueError("Unknown method")
