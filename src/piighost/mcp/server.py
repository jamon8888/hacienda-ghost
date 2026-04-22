from __future__ import annotations

import asyncio
import io
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP

from piighost.service.config import ServiceConfig
from piighost.service.core import PIIGhostService
from piighost.service.models import VaultEntryModel


def _harden_stdio_channel() -> None:
    """Isolate the JSON-RPC stdout channel from third-party noise.

    Why: stdio MCP uses fd 1 for protocol frames. Any library that prints
    to stdout (gliner2 model config banner, torch warnings, tqdm, etc.)
    corrupts the stream. On Windows, emoji prints also crash with
    UnicodeEncodeError under the default cp1252 codec.

    How: dup fd 1 to a private fd for the protocol, redirect fd 1 -> fd 2
    so OS-level stdout writes go to stderr, reroute sys.stdout to stderr
    so Python print() also lands on stderr, force UTF-8 on both stderr and
    stdin, and patch stdio_server() to use the saved protocol fd.
    """
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, OSError):
        pass
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    try:
        protocol_fd = os.dup(1)
    except OSError:
        return

    try:
        os.dup2(2, 1)
    except OSError:
        os.close(protocol_fd)
        return

    try:
        sys.stdout.flush()
    except Exception:
        pass
    sys.stdout = sys.stderr

    protocol_stream = io.TextIOWrapper(
        os.fdopen(protocol_fd, "wb", buffering=0),
        encoding="utf-8",
        write_through=True,
    )

    import anyio
    import mcp.server.stdio as _stdio_mod

    _original_stdio_server = _stdio_mod.stdio_server

    @asynccontextmanager
    async def _patched_stdio_server(stdin=None, stdout=None):
        if stdout is None:
            stdout = anyio.wrap_file(protocol_stream)
        async with _original_stdio_server(stdin=stdin, stdout=stdout) as streams:
            yield streams

    _stdio_mod.stdio_server = _patched_stdio_server
    for mod_name in (
        "fastmcp.server.low_level",
        "fastmcp.server.mixins.transport",
    ):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "stdio_server"):
            mod.stdio_server = _patched_stdio_server


def _indexing_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("sentence_transformers") is not None


async def build_mcp(vault_dir: Path) -> tuple[FastMCP, PIIGhostService]:
    config = ServiceConfig()
    svc = await PIIGhostService.create(vault_dir=vault_dir, config=config)
    mcp = FastMCP("piighost", "GDPR-compliant PII anonymization and document retrieval")

    @mcp.tool(description="Anonymize text, replacing PII with opaque tokens")
    async def anonymize_text(text: str, doc_id: str = "", project: str = "default") -> dict:
        result = await svc.anonymize(text, doc_id=doc_id or None, project=project)
        return result.model_dump()

    @mcp.tool(description="Rehydrate anonymized text back to original PII")
    async def rehydrate_text(text: str, project: str = "default") -> dict:
        result = await svc.rehydrate(text, project=project)
        return result.model_dump()

    if _indexing_available():
        @mcp.tool(description="Index a file or directory into the retrieval store")
        async def index_path(
            path: str,
            recursive: bool = True,
            force: bool = False,
            project: str = "",
        ) -> dict:
            project_arg = project if project else None
            report = await svc.index_path(
                Path(path), recursive=recursive, force=force, project=project_arg
            )
            return report.model_dump()

        @mcp.tool(description="Hybrid BM25+vector search over indexed documents")
        async def query(
            text: str,
            k: int = 5,
            project: str = "default",
            filter_prefix: str = "",
            filter_doc_ids: list[str] | None = None,
            rerank: bool = False,
            top_n: int = 20,
        ) -> dict:
            from piighost.indexer.filters import QueryFilter
            qfilter = None
            if filter_prefix or filter_doc_ids:
                qfilter = QueryFilter(
                    file_path_prefix=filter_prefix or None,
                    doc_ids=tuple(filter_doc_ids or ()),
                )
            result = await svc.query(
                text, k=k, project=project, filter=qfilter, rerank=rerank, top_n=top_n
            )
            return result.model_dump()

    @mcp.tool(description="Full-text search in the PII vault by original value")
    async def vault_search(
        q: str, reveal: bool = False, project: str = "default"
    ) -> list[dict]:
        entries = await svc.vault_search(q, reveal=reveal, project=project)
        return [e.model_dump() for e in entries]

    @mcp.tool(description="List vault entries with optional label filter")
    async def vault_list(
        label: str = "",
        limit: int = 100,
        offset: int = 0,
        reveal: bool = False,
        project: str = "default",
    ) -> list[dict]:
        page = await svc.vault_list(
            label=label or None,
            limit=limit,
            offset=offset,
            reveal=reveal,
            project=project,
        )
        return [e.model_dump(exclude_none=False) for e in page.entries]

    @mcp.tool(description="Retrieve a single vault entry by token")
    async def vault_get(
        token: str, reveal: bool = False, project: str = "default"
    ) -> dict | None:
        entry = await svc.vault_show(token, reveal=reveal, project=project)
        return entry.model_dump() if entry is not None else None

    @mcp.tool(description="Return vault statistics (total entries, by label)")
    async def vault_stats(project: str = "default") -> dict:
        stats = await svc.vault_stats(project=project)
        return stats.model_dump()

    @mcp.tool(description="List all projects")
    async def list_projects() -> list[dict]:
        projects = await svc.list_projects()
        return [
            {
                "name": p.name,
                "description": p.description,
                "created_at": p.created_at,
                "last_accessed_at": p.last_accessed_at,
            }
            for p in projects
        ]

    @mcp.tool(description="Create a new project")
    async def create_project(name: str, description: str = "") -> dict:
        info = await svc.create_project(name, description=description)
        return {
            "name": info.name,
            "description": info.description,
            "created_at": info.created_at,
        }

    @mcp.tool(description="Delete a project (refuses if non-empty unless force=True)")
    async def delete_project(name: str, force: bool = False) -> dict:
        deleted = await svc.delete_project(name, force=force)
        return {"deleted": deleted, "name": name}

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

    @mcp.resource("piighost://projects")
    async def projects_resource() -> str:
        import json
        projects = await svc.list_projects()
        payload = [
            {
                "name": p.name,
                "description": p.description,
                "created_at": p.created_at,
                "last_accessed_at": p.last_accessed_at,
            }
            for p in projects
        ]
        return json.dumps(payload, indent=2)

    @mcp.resource("piighost://projects/{name}/stats")
    async def project_stats_resource(name: str) -> str:
        stats = await svc.vault_stats(project=name)
        status = await svc.index_status(project=name)
        return (
            f"Project: {name}\n"
            f"Vault entities: {stats.total}\n"
            f"Indexed docs: {status.total_docs}\n"
            f"Total chunks: {status.total_chunks}\n"
        )

    # ------------------------------------------------------------------
    # Cowork plugin surface — folder-centric tools consumed by the
    # `hacienda` plugin skills (resolve / bootstrap / session audit /
    # folder status resource). Kept here (not in a separate module)
    # because they only make sense when exposed over MCP.
    # ------------------------------------------------------------------

    def _slug_for_folder(folder: Path) -> str:
        import hashlib
        import re
        abs_path = folder.resolve()
        raw_name = abs_path.name or "folder"
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw_name).strip("-").lower()[:40] or "folder"
        digest = hashlib.sha256(str(abs_path).encode("utf-8")).hexdigest()[:8]
        return f"{slug}-{digest}"

    def _sessions_dir() -> Path:
        path = vault_dir / "sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @mcp.tool(
        description=(
            "Resolve a deterministic project name from an absolute folder path. "
            "Returns {folder, project} where project is '<slug>-<hash8>'."
        )
    )
    async def resolve_project_for_folder(folder: str) -> dict:
        path = Path(folder).expanduser().resolve()
        return {"folder": str(path), "project": _slug_for_folder(path)}

    @mcp.tool(
        description=(
            "Idempotently provision the vault + project for a Cowork folder. "
            "Returns {folder, project, vault_key_provisioned}."
        )
    )
    async def bootstrap_client_folder(folder: str) -> dict:
        path = Path(folder).expanduser().resolve()
        project = _slug_for_folder(path)
        existing = {p.name for p in await svc.list_projects()}
        if project not in existing:
            await svc.create_project(
                project,
                description=f"Cowork folder: {path}",
            )
        return {
            "folder": str(path),
            "project": project,
            "vault_key_provisioned": True,
        }

    @mcp.tool(
        description=(
            "Append an audit entry to ~/.hacienda/sessions/<session_id>.audit.jsonl "
            "(session_id should be the project slug). Returns {path, line_count}."
        )
    )
    async def session_audit_append(
        session_id: str, event: str, payload: dict | None = None
    ) -> dict:
        import datetime as _dt
        import json

        log_file = _sessions_dir() / f"{session_id}.audit.jsonl"
        entry = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "event": event,
            "payload": payload or {},
        }
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        line_count = sum(1 for _ in log_file.open("r", encoding="utf-8"))
        return {"path": str(log_file), "line_count": line_count}

    @mcp.tool(
        description=(
            "Read all audit entries for a session (project slug). "
            "Returns {session_id, entries, count}."
        )
    )
    async def session_audit_read(session_id: str) -> dict:
        import json

        log_file = _sessions_dir() / f"{session_id}.audit.jsonl"
        if not log_file.exists():
            return {"session_id": session_id, "entries": [], "count": 0}
        entries: list[dict] = []
        with log_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {"session_id": session_id, "entries": entries, "count": len(entries)}

    @mcp.resource("piighost://folders/{b64_path}/status")
    async def folder_status_resource(b64_path: str) -> str:
        """Status for a Cowork folder — base64url-encoded absolute path.

        Returns JSON: {folder, project, state, total_docs, total_chunks,
        last_update, errors}. `state` is 'ready' when any docs are indexed,
        'empty' otherwise.
        """
        import base64
        import json

        padding = "=" * (-len(b64_path) % 4)
        try:
            decoded = base64.urlsafe_b64decode(b64_path + padding).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return json.dumps({"error": "invalid base64url-encoded path"})

        folder = Path(decoded).expanduser().resolve()
        project = _slug_for_folder(folder)
        try:
            status = await svc.index_status(project=project)
        except Exception:
            return json.dumps(
                {
                    "folder": str(folder),
                    "project": project,
                    "state": "empty",
                    "total_docs": 0,
                    "total_chunks": 0,
                    "last_update": None,
                    "errors": [],
                }
            )
        state = "ready" if status.total_docs > 0 else "empty"
        return json.dumps(
            {
                "folder": str(folder),
                "project": project,
                "state": state,
                "total_docs": status.total_docs,
                "total_chunks": status.total_chunks,
                "last_update": getattr(status, "last_update", None),
                "errors": list(getattr(status, "errors", []) or []),
            }
        )

    return mcp, svc


def run_mcp(vault_dir: Path, *, transport: str = "stdio") -> None:
    if transport == "stdio":
        _harden_stdio_channel()

    async def _start() -> None:
        mcp, svc = await build_mcp(vault_dir)
        try:
            await mcp.run_async(transport=transport)
        finally:
            await svc.close()

    asyncio.run(_start())
