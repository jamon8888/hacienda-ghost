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


def _build_retriever_class():
    """Lazy construction so langchain_core is only imported when used."""
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever
    from pydantic import ConfigDict

    class _PIIGhostRetriever(BaseRetriever):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        svc: Any
        project: str = "default"
        k: int = 5

        async def _aget_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
            result = await self.svc.query(query, project=self.project, k=self.k)
            return [
                Document(
                    page_content=hit.chunk,
                    metadata={
                        "doc_id": hit.doc_id,
                        "file_path": hit.file_path,
                        "score": hit.score,
                        "rank": hit.rank,
                        "project": self.project,
                    },
                )
                for hit in result.hits
            ]

        def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
            import asyncio
            return asyncio.run(self._aget_relevant_documents(query))

    return _PIIGhostRetriever


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

    @property
    def anonymizer(self) -> "Runnable[str, dict]":
        from langchain_core.runnables import RunnableLambda

        async def _run(text: str) -> dict:
            result = await self._svc.anonymize(text, project=self._project)
            return {
                "anonymized": result.anonymized,
                "entities": [
                    {"token": e.token, "label": e.label, "count": e.count}
                    for e in result.entities
                ],
            }

        return RunnableLambda(_run)

    @property
    def rehydrator(self) -> "Runnable[str, str]":
        from langchain_core.runnables import RunnableLambda

        async def _run(text: str) -> str:
            result = await self._svc.rehydrate(text, project=self._project, strict=False)
            return result.text

        return RunnableLambda(_run)

    @property
    def retriever(self) -> "BaseRetriever":
        retriever_cls = _build_retriever_class()
        return retriever_cls(svc=self._svc, project=self._project)
