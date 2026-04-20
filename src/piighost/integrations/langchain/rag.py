"""End-to-end RAG wrapper for LangChain backed by :class:`PIIGhostService`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from piighost.service.core import PIIGhostService
from piighost.service.models import IndexReport

if TYPE_CHECKING:
    from langchain_core.language_models import BaseLanguageModel
    from langchain_core.retrievers import BaseRetriever
    from langchain_core.runnables import Runnable


class PIIGhostRAG:
    """End-to-end PII-safe RAG chain backed by :class:`PIIGhostService`.

    One instance per project. Compose ``.anonymizer``, ``.retriever``,
    ``.rehydrator`` into custom chains, or call ``.as_chain(llm)`` for the
    standard pipeline.
    """

    def __init__(self, svc: PIIGhostService, *, project: str = "default") -> None:
        self._svc = svc
        self._project = project

    async def ingest(
        self,
        path: Path,
        *,
        recursive: bool = True,
        force: bool = False,
    ) -> IndexReport:
        return await self._svc.index_path(
            path, recursive=recursive, force=force, project=self._project
        )
