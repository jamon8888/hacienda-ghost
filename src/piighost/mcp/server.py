from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp import FastMCP

from piighost.service.config import ServiceConfig
from piighost.service.core import PIIGhostService


async def build_mcp(vault_dir: Path) -> tuple[FastMCP, PIIGhostService]:
    config = ServiceConfig()
    svc = await PIIGhostService.create(vault_dir=vault_dir, config=config)
    mcp = FastMCP("piighost", "GDPR-compliant PII anonymization and document retrieval")

    @mcp.tool(description="Anonymize text, replacing PII with opaque tokens")
    async def anonymize_text(text: str, doc_id: str = "") -> dict:
        result = await svc.anonymize(text, doc_id=doc_id or None)
        return result.model_dump()

    @mcp.tool(description="Rehydrate anonymized text back to original PII")
    async def rehydrate_text(text: str) -> dict:
        result = await svc.rehydrate(text)
        return result.model_dump()

    @mcp.tool(description="Index a file or directory into the retrieval store")
    async def index_path(path: str, recursive: bool = True) -> dict:
        report = await svc.index_path(Path(path), recursive=recursive)
        return report.model_dump()

    @mcp.tool(description="Hybrid BM25+vector search over indexed documents")
    async def query(text: str, k: int = 5) -> dict:
        result = await svc.query(text, k=k)
        return result.model_dump()

    @mcp.tool(description="Full-text search in the PII vault by original value")
    async def vault_search(q: str, reveal: bool = False) -> list[dict]:
        entries = await svc.vault_search(q, reveal=reveal)
        return [e.model_dump() for e in entries]

    @mcp.tool(description="List vault entries with optional label filter")
    async def vault_list(label: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
        entries = svc._vault.list_entities(
            label=label or None, limit=limit, offset=offset
        )
        from piighost.service.models import VaultEntryModel
        return [
            VaultEntryModel(
                token=e.token,
                label=e.label,
                original_masked=(e.original[:2] + "***" + e.original[-1:] if e.original else None),
                confidence=e.confidence,
                first_seen_at=e.first_seen_at,
                last_seen_at=e.last_seen_at,
                occurrence_count=e.occurrence_count,
            ).model_dump()
            for e in entries
        ]

    @mcp.tool(description="Retrieve a single vault entry by token")
    async def vault_get(token: str, reveal: bool = False) -> dict | None:
        entry = svc._vault.get_by_token(token)
        if entry is None:
            return None
        from piighost.service.models import VaultEntryModel
        return VaultEntryModel(
            token=entry.token,
            label=entry.label,
            original=entry.original if reveal else None,
            original_masked=(entry.original[:2] + "***" + entry.original[-1:] if entry.original else None),
            confidence=entry.confidence,
            first_seen_at=entry.first_seen_at,
            last_seen_at=entry.last_seen_at,
            occurrence_count=entry.occurrence_count,
        ).model_dump()

    @mcp.tool(description="Return vault statistics (total entries, by label)")
    async def vault_stats() -> dict:
        stats = svc._vault.stats()
        return {"total": stats.total, "by_label": stats.by_label}

    @mcp.tool(description="Check whether the piighost daemon is running")
    async def daemon_status() -> dict:
        from piighost.daemon.lifecycle import status
        hs = status(vault_dir)
        if hs is None:
            return {"running": False}
        return {"running": True, "pid": hs.pid, "port": hs.port}

    @mcp.tool(description="Stop the piighost daemon gracefully")
    async def daemon_stop() -> dict:
        from piighost.daemon.lifecycle import stop_daemon
        stopped = stop_daemon(vault_dir)
        return {"stopped": stopped}

    @mcp.resource("piighost://vault/stats")
    async def vault_stats_resource() -> str:
        stats = svc._vault.stats()
        return f"Total entities: {stats.total}\nBy label: {stats.by_label}"

    @mcp.resource("piighost://vault/recent")
    async def vault_recent_resource() -> str:
        entries = svc._vault.list_entities(limit=10)
        lines = [f"{e.token} [{e.label}] seen {e.occurrence_count}x" for e in entries]
        return "\n".join(lines) if lines else "(empty vault)"

    @mcp.resource("piighost://index/status")
    async def index_status_resource() -> str:
        records = svc._chunk_store.all_records()
        doc_ids = {r["doc_id"] for r in records}
        return f"Indexed documents: {len(doc_ids)}\nTotal chunks: {len(records)}"

    return mcp, svc


def run_mcp(vault_dir: Path, *, transport: str = "stdio") -> None:
    async def _start() -> None:
        mcp, svc = await build_mcp(vault_dir)
        try:
            await mcp.run_async(transport=transport)
        finally:
            await svc.close()

    asyncio.run(_start())
