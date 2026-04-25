"""The stateful core that CLI, daemon, and MCP all wrap."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import OrderedDict
from pathlib import Path
from typing import Protocol

from piighost.anonymizer import Anonymizer
from piighost.exceptions import PIISafetyViolation
from piighost.indexer.filters import QueryFilter
from piighost.models import Detection, Entity
from piighost.pipeline.base import AnonymizationPipeline
from piighost.placeholder import LabelHashPlaceholderFactory
from piighost.service.config import ServiceConfig
from piighost.service.errors import AnonymizationFailed
from piighost.service.models import (
    AnonymizeResult,
    CancelResult,
    DetectionResult,
    EntityRef,
    FolderChangesResult,
    IndexedFileEntry,
    IndexReport,
    IndexStatus,
    QueryResult,
    RehydrateResult,
    VaultEntryModel,
    VaultPage,
    VaultStatsModel,
)
from piighost.vault import AuditLogger, Vault, VaultEntry
from piighost.indexer.indexing_store import IndexingStore
from piighost.indexer.cancellation import CancellationToken, CancellationRegistry
from piighost.service.migration import migrate_to_v3
from piighost.vault.project_registry import ProjectRegistry, ProjectInfo

_TOKEN_RE = re.compile(r"<<[A-Z_]+:[0-9a-f]{8}>>")


class _Detector(Protocol):
    async def detect(self, text: str) -> list[Detection]: ...


class _ProjectService:
    """Stateful service. One instance per project directory."""

    def __init__(
        self,
        project_dir: Path,
        project_name: str,
        config: ServiceConfig,
        vault: Vault,
        audit: AuditLogger,
        detector: _Detector,
        ph_factory: LabelHashPlaceholderFactory,
        reranker=None,
    ) -> None:
        self._project_dir = project_dir
        self._project_name = project_name
        self._config = config
        self._vault = vault
        self._audit = audit
        self._detector = detector
        self._ph = ph_factory
        self._pipeline = AnonymizationPipeline(
            detector=detector,
            anonymizer=Anonymizer(ph_factory),
        )
        self._write_lock = asyncio.Lock()
        from piighost.indexer.embedder import build_embedder
        from piighost.indexer.store import ChunkStore
        from piighost.indexer.retriever import BM25Index

        self._embedder = build_embedder(config.embedder)
        self._chunk_store = ChunkStore(self._project_dir / ".piighost" / "lance")
        self._bm25 = BM25Index(self._project_dir / ".piighost" / "bm25.pkl")
        self._bm25.load()
        self._reranker = reranker
        self._indexing_store = IndexingStore.open(
            self._project_dir / "indexing.sqlite"
        )
        self._cancel_token: CancellationToken | None = None

    @classmethod
    async def create(
        cls,
        *,
        project_dir: Path,
        project_name: str,
        config: ServiceConfig | None = None,
        detector: _Detector | None = None,
        placeholder_salt: str = "",
        reranker=None,
    ) -> "_ProjectService":
        config = config or ServiceConfig.default()
        project_dir.mkdir(parents=True, exist_ok=True)
        vault = Vault.open(project_dir / "vault.db")
        audit = AuditLogger(project_dir / "audit.log")
        if detector is None:
            detector = await _build_default_detector(config)
        if reranker is None:
            reranker = await _build_default_reranker(config)
        return cls(
            project_dir=project_dir,
            project_name=project_name,
            config=config,
            vault=vault,
            audit=audit,
            detector=detector,
            ph_factory=LabelHashPlaceholderFactory(),
            reranker=reranker,
        )

    # ---- core ops ----

    def _token_for(self, entity: Entity) -> str:
        """Recompute the deterministic hash token for an entity."""
        return self._ph.create([entity])[entity]

    async def anonymize(
        self, text: str, *, doc_id: str | None = None
    ) -> AnonymizeResult:
        doc_id = (
            doc_id
            or f"anon-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:10]}"
        )
        try:
            anonymized, entities = await self._pipeline.anonymize(text)
        except Exception as exc:
            raise AnonymizationFailed(
                doc_id=doc_id, stage="pipeline", entity_count=0
            ) from exc
        if not entities:
            return AnonymizeResult(
                doc_id=doc_id,
                anonymized=text,
                entities=[],
                stats={"chars_in": len(text), "chars_out": len(text)},
            )

        async with self._write_lock:
            for ent in entities:
                token = self._token_for(ent)
                confidence = max(
                    (d.confidence for d in ent.detections if d.confidence is not None),
                    default=None,
                )
                self._vault.upsert_entity(
                    token=token,
                    original=ent.detections[0].text,
                    label=ent.label,
                    confidence=confidence,
                )
                for det in ent.detections:
                    self._vault.link_doc_entity(
                        doc_id=doc_id,
                        token=token,
                        start_pos=det.position.start_pos,
                        end_pos=det.position.end_pos,
                    )

        refs = [
            EntityRef(
                token=self._token_for(ent),
                label=ent.label,
                count=len(ent.detections),
            )
            for ent in entities
        ]
        return AnonymizeResult(
            doc_id=doc_id,
            anonymized=anonymized,
            entities=refs,
            stats={"chars_in": len(text), "chars_out": len(anonymized)},
        )

    async def rehydrate(
        self, text: str, *, strict: bool | None = None
    ) -> RehydrateResult:
        strict = self._config.safety.strict_rehydrate if strict is None else strict
        tokens = _TOKEN_RE.findall(text)
        unknown: list[str] = []
        result = text
        # longest tokens first avoids prefix-clash
        for tok in sorted(set(tokens), key=len, reverse=True):
            entry = self._vault.get_by_token(tok)
            if entry is None:
                unknown.append(tok)
                continue
            result = result.replace(tok, entry.original)
            self._audit.record(op="rehydrate", token=tok, caller_kind="service")
        if unknown and strict:
            raise PIISafetyViolation(
                f"rehydrate: {len(unknown)} unknown tokens in strict mode"
            )
        return RehydrateResult(text=result, unknown_tokens=unknown)

    async def detect(self, text: str) -> list[DetectionResult]:
        dets = await self._detector.detect(text)
        return [
            DetectionResult(
                text=d.text,
                label=d.label,
                start=d.position.start_pos,
                end=d.position.end_pos,
                confidence=d.confidence,
            )
            for d in dets
        ]

    async def index_path(
        self, path: Path, *, recursive: bool = True, force: bool = False,
        cancel_token: "CancellationToken | None" = None,
    ) -> "IndexReport":
        import time as _time

        from piighost.indexer.chunker import chunk_text
        from piighost.indexer.identity import content_hash_full, file_fingerprint
        from piighost.indexer.ingestor import extract_text, list_document_paths
        from piighost.indexer.indexing_store import FileRecord, backfill_from_vault
        from piighost.indexer.change_detector import ChangeDetector
        from piighost.service.models import IndexReport

        # One-shot migration from legacy vault rows (idempotent after first call)
        backfill_from_vault(self._indexing_store, self._vault, self._project_name)

        start = _time.monotonic()
        indexed = modified = deleted_count = skipped = unchanged = 0
        errors: list[str] = []

        if force:
            # full re-index — treat every file as new
            paths = await list_document_paths(path, recursive=recursive)
            targets = [(p.resolve(), "new") for p in paths]
            unchanged_paths: list[Path] = []
            deleted_paths: list[Path] = []
        else:
            detector = ChangeDetector(
                store=self._indexing_store, project_id=self._project_name
            )
            cs = await detector.scan_async(path, recursive=recursive)
            targets = (
                [(p, "new") for p in cs.new]
                + [(p, "modified") for p in cs.modified]
            )
            unchanged_paths = cs.unchanged
            deleted_paths = cs.deleted

        unchanged = len(unchanged_paths)

        # NOTE: batch() opens BEGIN IMMEDIATE and holds it across the async
        # I/O loop below (extract_text + anonymize + embed).  This is safe for
        # the single-threaded asyncio event loop used by the MCP server — only
        # one coroutine runs at a time, so no second caller can attempt a
        # concurrent BEGIN IMMEDIATE on the same connection.  If you add a
        # concurrent caller in the future, move the upsert() calls outside the
        # batch() and flush results in a second synchronous pass.
        with self._indexing_store.batch():
            # Handle deletions first
            for p in deleted_paths:
                self._indexing_store.mark_deleted(self._project_name, str(p))
                existing = self._vault.get_indexed_file_by_path(str(p))
                if existing is not None:
                    self._chunk_store.delete_doc(existing.doc_id)
                    self._vault.delete_doc_entities(existing.doc_id)
                    self._vault.delete_indexed_file(existing.doc_id)
                deleted_count += 1

            # Process additions and modifications
            for p, kind in targets:
                if cancel_token is not None and cancel_token.is_cancelled:
                    break
                try:
                    stat_mtime, stat_size = file_fingerprint(p)
                    text = await extract_text(p)
                    if text is None:
                        skipped += 1
                        continue
                    chash_full = content_hash_full(p)
                    doc_id = chash_full[:16]

                    # If replacing existing doc, clean up old vectors first
                    existing = self._vault.get_indexed_file_by_path(str(p))
                    if existing is not None:
                        self._chunk_store.delete_doc(existing.doc_id)
                        if existing.doc_id != doc_id:
                            self._vault.delete_doc_entities(existing.doc_id)
                            self._vault.delete_indexed_file(existing.doc_id)

                    result = await self.anonymize(text, doc_id=doc_id)
                    chunks = chunk_text(result.anonymized)
                    if not chunks:
                        skipped += 1
                        continue

                    vectors = await self._embedder.embed(chunks)
                    self._chunk_store.upsert_chunks(doc_id, str(p), chunks, vectors)
                    self._vault.upsert_indexed_file(
                        doc_id=doc_id, file_path=str(p),
                        content_hash=doc_id, mtime=stat_mtime,
                        chunk_count=len(chunks),
                    )
                    self._indexing_store.upsert(FileRecord(
                        project_id=self._project_name,
                        file_path=str(p),
                        file_mtime=stat_mtime,
                        file_size=stat_size,
                        content_hash=chash_full,
                        indexed_at=_time.time(),
                        status="success",
                        error_message=None,
                        entity_count=len(result.entities),
                        chunk_count=len(chunks),
                    ))
                    if kind == "modified":
                        modified += 1
                    else:
                        indexed += 1
                except Exception as exc:  # noqa: BLE001 — per-file isolation
                    err_msg = f"{p.name}: {type(exc).__name__}"
                    errors.append(err_msg)
                    try:
                        stat_mtime, stat_size = file_fingerprint(p)
                    except OSError:
                        stat_mtime, stat_size = 0.0, 0
                    self._indexing_store.upsert(FileRecord(
                        project_id=self._project_name,
                        file_path=str(p),
                        file_mtime=stat_mtime,
                        file_size=stat_size,
                        content_hash="",
                        indexed_at=_time.time(),
                        status="error",
                        error_message=f"{type(exc).__name__}: {exc}",
                        entity_count=None,
                        chunk_count=None,
                    ))

        if indexed > 0 or modified > 0 or deleted_count > 0 or errors:
            all_records = self._chunk_store.all_records()
            if all_records:
                self._bm25.rebuild(all_records)
            else:
                self._bm25.clear()

        duration_ms = int((_time.monotonic() - start) * 1000)
        return IndexReport(
            indexed=indexed,
            modified=modified,
            deleted=deleted_count,
            skipped=skipped,
            unchanged=unchanged,
            errors=errors,
            duration_ms=duration_ms,
        )

    async def remove_doc(self, path: Path) -> bool:
        existing = self._vault.get_indexed_file_by_path(str(path.resolve()))
        if existing is None:
            return False
        # Delete vault records first so a crash before LanceDB cleanup leaves the
        # file eligible for re-indexing on the next index_path call.
        self._vault.delete_doc_entities(existing.doc_id)
        self._vault.delete_indexed_file(existing.doc_id)
        self._chunk_store.delete_doc(existing.doc_id)
        all_records = self._chunk_store.all_records()
        if all_records:
            self._bm25.rebuild(all_records)
        else:
            self._bm25.clear()
        return True

    async def index_status(
        self, *, limit: int = 100, offset: int = 0
    ) -> IndexStatus:
        total_docs = self._vault.count_indexed_files()
        total_chunks = self._vault.total_chunk_count()
        files = self._vault.list_indexed_files(limit=limit, offset=offset)
        entries = [
            IndexedFileEntry(
                doc_id=f.doc_id,
                file_path=f.file_path,
                indexed_at=f.indexed_at,
                chunk_count=f.chunk_count,
            )
            for f in files
        ]
        return IndexStatus(
            total_docs=total_docs,
            total_chunks=total_chunks,
            files=entries,
        )

    async def query(
        self,
        text: str,
        *,
        k: int = 5,
        filter: "QueryFilter | None" = None,
        rerank: bool = False,
        top_n: int = 20,
    ) -> "QueryResult":
        from piighost.indexer.retriever import reciprocal_rank_fusion
        from piighost.service.models import QueryHit, QueryResult

        if rerank and self._reranker is None:
            raise ValueError(
                "rerank=True but no reranker configured; "
                "set ServiceConfig.reranker.backend to 'cross_encoder'"
            )

        fetch_k = max(top_n, k) if rerank else k

        anon_result = await self.anonymize(text)
        anon_query = anon_result.anonymized

        bm25_hits = self._bm25.search(anon_query, k=fetch_k * 2, filter=filter)
        query_vecs = await self._embedder.embed([anon_query])
        vec_hits_raw = self._chunk_store.vector_search(query_vecs[0], k=fetch_k * 2, filter=filter)
        vector_hits = [(r["chunk_id"], r.get("_distance", 0.0)) for r in vec_hits_raw]

        fused = reciprocal_rank_fusion(bm25_hits, vector_hits, rrf_k=60)[:fetch_k]

        all_records = {r["chunk_id"]: r for r in self._chunk_store.all_records()}
        hits: list[QueryHit] = []
        for rank, (chunk_id, score) in enumerate(fused):
            rec = all_records.get(chunk_id)
            if rec is None:
                continue
            hits.append(
                QueryHit(
                    doc_id=rec["doc_id"],
                    file_path=rec["file_path"],
                    chunk=rec["chunk"],
                    score=score,
                    rank=rank,
                )
            )

        if rerank:
            hits = await self._reranker.rerank(text, hits)
            hits = hits[:k]

        return QueryResult(query=text, hits=hits, k=k)

    # ---- vault ops ----

    async def vault_list(
        self,
        *,
        label: str | None = None,
        limit: int = 100,
        offset: int = 0,
        reveal: bool = False,
    ) -> VaultPage:
        rows = self._vault.list_entities(label=label, limit=limit, offset=offset)
        entries = [self._to_entry_model(r, reveal=reveal) for r in rows]
        return VaultPage(entries=entries)

    async def vault_show(
        self, token: str, *, reveal: bool = False
    ) -> VaultEntryModel | None:
        row = self._vault.get_by_token(token)
        if row is None:
            return None
        if reveal:
            self._audit.record(
                op="vault_show_reveal", token=token, caller_kind="service"
            )
        return self._to_entry_model(row, reveal=reveal)

    async def vault_stats(self) -> VaultStatsModel:
        s = self._vault.stats()
        return VaultStatsModel(total=s.total, by_label=s.by_label)

    async def vault_search(
        self, query: str, *, reveal: bool = False, limit: int = 100
    ) -> list[VaultEntryModel]:
        entries = self._vault.search_entities(query, limit=limit)
        return [self._to_entry_model(e, reveal=reveal) for e in entries]

    async def check_folder_changes(
        self, folder: Path, *, recursive: bool = True
    ) -> "FolderChangesResult":
        from piighost.indexer.change_detector import ChangeDetector
        from piighost.indexer.batch_scheduler import classify_batch
        from piighost.service.models import FolderChangesResult, FileChangeEntry
        from piighost.indexer.indexing_store import backfill_from_vault

        backfill_from_vault(self._indexing_store, self._vault, self._project_name)
        det = ChangeDetector(store=self._indexing_store, project_id=self._project_name)
        cs = await det.scan_async(folder, recursive=recursive)
        tier = classify_batch(cs, self._config.incremental)

        def _entry(p: Path) -> FileChangeEntry:
            try:
                return FileChangeEntry(file_path=str(p), size=p.stat().st_size)
            except OSError:
                return FileChangeEntry(file_path=str(p), size=0)

        return FolderChangesResult(
            folder=str(folder),
            project=self._project_name,
            new=[_entry(p) for p in cs.new],
            modified=[_entry(p) for p in cs.modified],
            deleted=[str(p) for p in cs.deleted],
            unchanged_count=len(cs.unchanged),
            tier=tier.value,
        )

    # ---- lifecycle ----

    async def flush(self) -> None:
        # autocommit mode — nothing to flush. Reserved for future buffered writes.
        pass

    async def close(self) -> None:
        self._indexing_store.close()
        self._vault.close()

    # ---- helpers ----

    @staticmethod
    def _mask(original: str) -> str:
        if len(original) <= 2:
            return "*" * len(original)
        return original[0] + "*" * (len(original) - 2) + original[-1]

    def _to_entry_model(self, v: VaultEntry, *, reveal: bool) -> VaultEntryModel:
        return VaultEntryModel(
            token=v.token,
            label=v.label,
            original=v.original if reveal else None,
            original_masked=self._mask(v.original),
            confidence=v.confidence,
            first_seen_at=v.first_seen_at,
            last_seen_at=v.last_seen_at,
            occurrence_count=v.occurrence_count,
        )


class PIIGhostService:
    """Multiplexer over per-project :class:`_ProjectService` instances."""

    LRU_SIZE = 8

    def __init__(
        self,
        vault_dir: Path,
        config: ServiceConfig,
        registry: ProjectRegistry,
    ) -> None:
        self._vault_dir = vault_dir
        self._config = config
        self._registry = registry
        self._cache: "OrderedDict[str, _ProjectService]" = OrderedDict()
        self._detector_override: _Detector | None = None
        self._cancel_registry = CancellationRegistry()

    @classmethod
    async def create(
        cls,
        *,
        vault_dir: Path,
        config: ServiceConfig | None = None,
        detector: _Detector | None = None,
    ) -> "PIIGhostService":
        config = config or ServiceConfig.default()
        migrate_to_v3(vault_dir)
        registry = ProjectRegistry.open(vault_dir / "projects.db")
        svc = cls(vault_dir=vault_dir, config=config, registry=registry)
        svc._detector_override = detector
        return svc

    async def _get_project(
        self, name: str, *, auto_create: bool = False
    ) -> "_ProjectService":
        if name in self._cache:
            self._cache.move_to_end(name)
            self._registry.touch(name)
            return self._cache[name]

        info = self._registry.get(name)
        if info is None:
            if not auto_create:
                from piighost.exceptions import ProjectNotFound
                raise ProjectNotFound(name)
            info = self._registry.create(name)

        project_dir = self._vault_dir / "projects" / name
        svc = await _ProjectService.create(
            project_dir=project_dir,
            project_name=name,
            config=self._config,
            detector=self._detector_override,
            placeholder_salt=info.placeholder_salt,
        )
        self._cache[name] = svc
        while len(self._cache) > self.LRU_SIZE:
            _evicted_name, evicted_svc = self._cache.popitem(last=False)
            await evicted_svc.close()
        self._registry.touch(name)
        return svc

    async def anonymize(self, text: str, *, doc_id: str | None = None, project: str = "default"):
        svc = await self._get_project(project, auto_create=True)
        return await svc.anonymize(text, doc_id=doc_id)

    async def rehydrate(self, text: str, *, strict: bool | None = None, project: str = "default"):
        svc = await self._get_project(project)
        return await svc.rehydrate(text, strict=strict)

    async def detect(self, text: str, *, project: str = "default"):
        svc = await self._get_project(project)
        return await svc.detect(text)

    async def index_path(
        self,
        path: Path,
        *,
        recursive: bool = True,
        force: bool = False,
        project: str | None = None,
    ):
        from piighost.service.project_path import derive_project_from_path
        resolved = project if project is not None else derive_project_from_path(path)
        svc = await self._get_project(resolved, auto_create=True)
        cancel_token = self._cancel_registry.get_or_create(resolved)
        report = await svc.index_path(
            path, recursive=recursive, force=force, cancel_token=cancel_token,
        )
        # Reset so next run starts fresh
        self._cancel_registry.reset(resolved)
        return report.model_copy(update={"project": resolved})

    async def check_folder_changes(
        self,
        folder: str,
        *,
        recursive: bool = True,
        project: str | None = None,
    ) -> "FolderChangesResult":
        from piighost.service.project_path import derive_project_from_path
        folder_path = Path(folder).expanduser().resolve()
        resolved = project if project is not None else derive_project_from_path(folder_path)
        svc = await self._get_project(resolved, auto_create=True)
        return await svc.check_folder_changes(folder_path, recursive=recursive)

    async def cancel_indexing(self, *, project: str = "default") -> "CancelResult":
        from piighost.service.models import CancelResult
        token = self._cancel_registry.get_or_create(project)
        token.cancel()
        return CancelResult(project=project, cancelled=True)

    async def remove_doc(self, path: Path, *, project: str = "default") -> bool:
        svc = await self._get_project(project)
        return await svc.remove_doc(path)

    async def query(
        self,
        text: str,
        *,
        k: int = 5,
        project: str = "default",
        filter: "QueryFilter | None" = None,
        rerank: bool = False,
        top_n: int = 20,
    ):
        svc = await self._get_project(project)
        return await svc.query(text, k=k, filter=filter, rerank=rerank, top_n=top_n)

    async def index_status(self, *, limit: int = 100, offset: int = 0, project: str = "default"):
        svc = await self._get_project(project)
        return await svc.index_status(limit=limit, offset=offset)

    async def vault_list(
        self,
        *,
        label: str | None = None,
        limit: int = 100,
        offset: int = 0,
        reveal: bool = False,
        project: str = "default",
    ):
        svc = await self._get_project(project)
        return await svc.vault_list(
            label=label, limit=limit, offset=offset, reveal=reveal
        )

    async def vault_show(self, token: str, *, reveal: bool = False, project: str = "default"):
        svc = await self._get_project(project)
        return await svc.vault_show(token, reveal=reveal)

    async def vault_stats(self, *, project: str = "default"):
        svc = await self._get_project(project)
        return await svc.vault_stats()

    async def vault_search(
        self,
        query: str,
        *,
        reveal: bool = False,
        limit: int = 100,
        project: str = "default",
    ):
        svc = await self._get_project(project)
        return await svc.vault_search(query, reveal=reveal, limit=limit)

    async def list_projects(self) -> "list[ProjectInfo]":
        return self._registry.list()

    async def create_project(
        self, name: str, description: str = "", placeholder_salt: str | None = None
    ) -> "ProjectInfo":
        return self._registry.create(
            name, description=description, placeholder_salt=placeholder_salt
        )

    async def delete_project(self, name: str, *, force: bool = False) -> bool:
        if name == "default":
            raise ValueError("the default project cannot be deleted")

        info = self._registry.get(name)
        if info is None:
            return False

        if not force:
            svc = await self._get_project(name)
            stats = await svc.vault_stats()
            status = await svc.index_status()
            if stats.total > 0 or status.total_docs > 0:
                from piighost.exceptions import ProjectNotEmpty
                raise ProjectNotEmpty(
                    name=name,
                    doc_count=status.total_docs,
                    vault_count=stats.total,
                )

        cached = self._cache.pop(name, None)
        if cached is not None:
            await cached.close()

        import shutil
        project_dir = self._vault_dir / "projects" / name
        if project_dir.exists():
            shutil.rmtree(project_dir)
        return self._registry.delete(name)

    async def flush(self) -> None:
        for svc in self._cache.values():
            await svc.flush()

    async def close(self) -> None:
        for svc in self._cache.values():
            await svc.close()
        self._cache.clear()
        self._registry.close()


async def _build_default_reranker(config: ServiceConfig):
    if config.reranker.backend == "none":
        return None
    if config.reranker.backend == "cross_encoder":
        from piighost.reranker.cross_encoder import CrossEncoderReranker
        return CrossEncoderReranker(config.reranker.cross_encoder_model)
    raise NotImplementedError(f"reranker backend {config.reranker.backend!r}")


async def _build_default_detector(config: ServiceConfig) -> _Detector:
    """Load a detector based on config. Deferred import keeps cold start lean."""
    import os

    if os.environ.get("PIIGHOST_DETECTOR") == "stub":
        return _StubDetector()
    if config.detector.backend == "regex_only":
        from piighost.detector.regex import RegexDetector

        return RegexDetector()
    if config.detector.backend == "gliner2":
        from gliner2 import GLiNER2

        from piighost.detector.gliner2 import Gliner2Detector

        model = GLiNER2.from_pretrained(config.detector.gliner2_model)
        ner = Gliner2Detector(
            model=model,
            labels=config.detector.labels,
            threshold=config.detector.threshold,
        )
        if config.detector.regex_fallback:
            from piighost.detector.base import CompositeDetector
            from piighost.detector.regex import RegexDetector

            return CompositeDetector(detectors=[ner, RegexDetector()])
        return ner
    raise NotImplementedError(
        f"detector backend {config.detector.backend!r} not shipped yet"
    )


class _StubDetector:
    """Deterministic stub used only when ``PIIGHOST_DETECTOR=stub`` (tests/dev)."""

    async def detect(self, text: str) -> list[Detection]:
        from piighost.models import Detection, Span

        out: list[Detection] = []
        for needle, label in (("Alice", "PERSON"), ("Paris", "LOC")):
            start = 0
            while True:
                idx = text.find(needle, start)
                if idx < 0:
                    break
                out.append(
                    Detection(
                        text=needle,
                        label=label,
                        position=Span(start_pos=idx, end_pos=idx + len(needle)),
                        confidence=0.99,
                    )
                )
                start = idx + len(needle)
        return out
