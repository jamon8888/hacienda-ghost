"""Starlette app for the anonymizing proxy."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Protocol

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from piighost.proxy.audit import AuditRecord, AuditWriter
from piighost.proxy.rewrite_request import rewrite_request_body
from piighost.proxy.rewrite_response import rewrite_sse_stream
from piighost.proxy.upstream import AnthropicUpstream


class Service(Protocol):
    async def anonymize(self, text: str, *, project: str) -> tuple[str, dict[str, Any]]: ...
    async def rehydrate(self, text: str, *, project: str) -> str: ...
    async def active_project(self) -> str: ...


def build_app(
    *,
    service: Service,
    vault_dir: Path,
    upstream_base_url: str = "https://api.anthropic.com",
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    token: str = "",
) -> Starlette:
    upstream = AnthropicUpstream(
        base_url=upstream_base_url,
        transport=upstream_transport,
    )
    audit = AuditWriter(root=vault_dir / "audit")

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def probe(_: Request) -> JSONResponse:
        return JSONResponse({"intercepted": True, "proxy": "piighost"})

    async def messages(request: Request) -> StreamingResponse | JSONResponse:
        # Paused mode: skip anonymization and forward as-is. The daemon stays
        # running so strict-mode hosts redirects keep resolving, but PII
        # rewriting is disabled. Toggled via `piighost on` / `piighost off`,
        # which create/remove <vault>/paused.
        if (vault_dir / "paused").exists():
            return await passthrough(request)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        try:
            project = await service.active_project()
        except Exception as exc:
            return JSONResponse(
                {"error": f"no active project: {exc}"}, status_code=409
            )

        try:
            rewritten, meta = await rewrite_request_body(
                body, service, project=project
            )
        except Exception as exc:
            return JSONResponse({"error": f"anonymization failed: {exc}"}, status_code=500)

        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() in {
                "authorization", "x-api-key",
                "anthropic-version", "anthropic-beta",
                "content-type",
            }
        }

        started = time.monotonic()
        try:
            upstream_resp = await upstream.post(
                "/v1/messages", json=rewritten, headers=headers
            )
        except Exception as exc:
            return JSONResponse({"error": f"upstream unreachable: {exc}"}, status_code=502)

        async def body_iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in rewrite_sse_stream(
                    upstream_resp.aiter_bytes(), service, project=project
                ):
                    yield chunk
            finally:
                await upstream_resp.aclose()
                audit.write(
                    AuditRecord(
                        ts=datetime.now(timezone.utc),
                        request_id=str(uuid.uuid4()),
                        project=project,
                        host=request.headers.get("user-agent", "unknown"),
                        model=rewritten.get("model", ""),
                        entities_detected=meta.get("entities", []),
                        placeholders_emitted=len(meta.get("entities", [])),
                        request_bytes_in=len(str(body)),
                        request_bytes_out=len(str(rewritten)),
                        stream_duration_ms=int((time.monotonic() - started) * 1000),
                        rehydration_errors=0,
                        status="ok",
                    )
                )

        return StreamingResponse(
            body_iter(),
            status_code=upstream_resp.status_code,
            media_type=upstream_resp.headers.get("content-type", "text/event-stream"),
        )

    async def passthrough(request: Request) -> StreamingResponse | JSONResponse:
        """Forward any unrecognised path directly to the upstream without anonymization."""
        _PASSTHROUGH_HEADERS = {
            "authorization", "x-api-key", "anthropic-version",
            "anthropic-beta", "content-type", "accept", "user-agent",
        }
        fwd_headers = {
            k: v for k, v in request.headers.items()
            if k.lower() in _PASSTHROUGH_HEADERS
        }
        body = await request.body()
        try:
            resp = await upstream.request(
                method=request.method,
                path=request.url.path,
                params=str(request.url.query) if request.url.query else None,
                content=body or None,
                headers=fwd_headers,
            )
        except Exception as exc:
            return JSONResponse({"error": f"upstream unreachable: {exc}"}, status_code=502)

        async def _iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose()

        return StreamingResponse(
            _iter(),
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    @asynccontextmanager
    async def _lifespan(app_: Starlette):
        yield
        await upstream.aclose()

    return Starlette(
        lifespan=_lifespan,
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/piighost-probe", probe, methods=["GET"]),
            Route("/v1/messages", messages, methods=["POST"]),
            Route("/{path:path}", passthrough, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]),
        ]
    )
