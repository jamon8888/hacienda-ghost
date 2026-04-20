# piighost Sprint 6a — RAG Wrappers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `PIIGhostRAG` (LangChain) and `build_piighost_rag` (Haystack) convenience wrappers so users get a working PII-safe RAG in ~5 lines. Fix the one broken LangChain test that blocks the suite.

**Architecture:** Both wrappers compose `PIIGhostService` (Sprint 5 multiplexer) — they own no state beyond a service reference + project name. LangChain side exposes a class with `.ingest()`, `.query(llm)`, and individual `.anonymizer` / `.retriever` / `.rehydrator` LCEL runnables. Haystack side exposes a `PIIGhostRetriever` component + a `build_piighost_rag(svc, llm_generator)` factory that returns a pre-wired `Pipeline`.

**Tech Stack:** Python 3.10+, LangChain 1.x (+ langchain-community), Haystack-ai 2.x, PIIGhostService (Sprint 5), existing `PIIGhostQueryAnonymizer` / `PIIGhostRehydrator` from prior sprints.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `tests/integrations/langchain/test_hybrid_retrieval.py:17` | Fix broken import (`langchain.retrievers` → `langchain_community.retrievers`) |
| Create | `src/piighost/integrations/langchain/rag.py` | `PIIGhostRAG` class + `_PIIGhostRetriever` BaseRetriever + prompt template |
| Modify | `src/piighost/integrations/langchain/__init__.py` | Re-export `PIIGhostRAG` |
| Create | `src/piighost/integrations/haystack/rag.py` | `PIIGhostRetriever` component + `build_piighost_rag` factory |
| Modify | `src/piighost/integrations/haystack/__init__.py` | Re-export `PIIGhostRetriever`, `build_piighost_rag` |
| Create | `tests/integrations/langchain/test_rag.py` | Unit tests for `PIIGhostRAG` |
| Create | `tests/integrations/haystack/test_rag_pipeline.py` | Unit tests for the Haystack factory |
| Create | `tests/e2e/test_langchain_rag_roundtrip.py` | End-to-end LangChain RAG with fake LLM + PII leak check |
| Create | `tests/e2e/test_haystack_rag_roundtrip.py` | End-to-end Haystack RAG with fake generator + PII leak check |

---

### Task 1: Fix broken `test_hybrid_retrieval.py` import

**Files:**
- Modify: `tests/integrations/langchain/test_hybrid_retrieval.py`

- [ ] **Step 1: Verify failure**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
python -m pytest tests/integrations/langchain/test_hybrid_retrieval.py --collect-only 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'langchain.retrievers'`.

- [ ] **Step 2: Fix the import**

In `tests/integrations/langchain/test_hybrid_retrieval.py`, find line 17:

```python
from langchain.retrievers import EnsembleRetriever  # noqa: E402
```

Replace with:

```python
from langchain_community.retrievers import EnsembleRetriever  # noqa: E402
```

- [ ] **Step 3: Verify collection succeeds**

```bash
python -m pytest tests/integrations/langchain/test_hybrid_retrieval.py --collect-only 2>&1 | tail -5
```

Expected: test(s) collected without import errors.

- [ ] **Step 4: Run the fixed test**

```bash
python -m pytest tests/integrations/langchain/test_hybrid_retrieval.py -v -p no:randomly 2>&1 | tail -20
```

Expected: tests pass (or skip cleanly if marked `@pytest.mark.slow`).

- [ ] **Step 5: Run full LangChain integration suite**

```bash
python -m pytest tests/integrations/langchain/ -v -p no:randomly 2>&1 | tail -15
```

Expected: no import failures, all tests either pass or skip cleanly.

- [ ] **Step 6: Commit**

```bash
git add tests/integrations/langchain/test_hybrid_retrieval.py
git commit -m "fix(tests/integrations/langchain): EnsembleRetriever moved to langchain_community"
```

---

### Task 2: LangChain `PIIGhostRAG` — construction + `.ingest()`

**Files:**
- Create: `src/piighost/integrations/langchain/rag.py`
- Modify: `src/piighost/integrations/langchain/__init__.py`
- Create: `tests/integrations/langchain/test_rag.py`

- [ ] **Step 1: Write failing test**

Create `tests/integrations/langchain/test_rag.py`:

```python
import asyncio

import pytest

pytest.importorskip("langchain_core")

from piighost.integrations.langchain.rag import PIIGhostRAG
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


def test_construct_with_service(svc):
    rag = PIIGhostRAG(svc)
    assert rag is not None


def test_construct_with_project(svc):
    rag = PIIGhostRAG(svc, project="client-a")
    assert rag._project == "client-a"


def test_ingest_delegates_to_service(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="client-a")
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    report = asyncio.run(rag.ingest(doc))
    assert report.indexed >= 1
    assert report.project == "client-a"
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: `ModuleNotFoundError: No module named 'piighost.integrations.langchain.rag'`.

- [ ] **Step 3: Create `src/piighost/integrations/langchain/rag.py`**

```python
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
```

- [ ] **Step 4: Update `src/piighost/integrations/langchain/__init__.py`**

Read the existing file. Append the export:

```python
from piighost.integrations.langchain.rag import PIIGhostRAG  # noqa: F401
```

Add `"PIIGhostRAG"` to `__all__` if the module defines one.

- [ ] **Step 5: Run tests — should pass**

```bash
python -m pytest tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/integrations/langchain/rag.py \
        src/piighost/integrations/langchain/__init__.py \
        tests/integrations/langchain/test_rag.py
git commit -m "feat(integrations/langchain): PIIGhostRAG skeleton with .ingest()"
```

---

### Task 3: LangChain — `.anonymizer` and `.rehydrator` runnables

**Files:**
- Modify: `src/piighost/integrations/langchain/rag.py`
- Modify: `tests/integrations/langchain/test_rag.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/integrations/langchain/test_rag.py`:

```python
def test_anonymizer_is_runnable(svc):
    rag = PIIGhostRAG(svc, project="client-a")
    result = asyncio.run(rag.anonymizer.ainvoke("Alice lives in Paris"))
    assert "anonymized" in result
    assert "entities" in result
    assert "Alice" not in result["anonymized"]


def test_rehydrator_roundtrip(svc):
    rag = PIIGhostRAG(svc, project="client-a")
    anon = asyncio.run(rag.anonymizer.ainvoke("Alice lives in Paris"))
    rehydrated = asyncio.run(rag.rehydrator.ainvoke(anon["anonymized"]))
    assert "Alice" in rehydrated


def test_anonymizer_project_scoped(svc):
    rag_a = PIIGhostRAG(svc, project="client-a")
    rag_b = PIIGhostRAG(svc, project="client-b")
    result_a = asyncio.run(rag_a.anonymizer.ainvoke("Alice"))
    result_b = asyncio.run(rag_b.anonymizer.ainvoke("Alice"))
    a_tokens = {e["token"] for e in result_a["entities"]}
    b_tokens = {e["token"] for e in result_b["entities"]}
    assert a_tokens.isdisjoint(b_tokens)
```

- [ ] **Step 2: Run tests — should fail**

```bash
python -m pytest tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: `AttributeError: 'PIIGhostRAG' object has no attribute 'anonymizer'`.

- [ ] **Step 3: Add `.anonymizer` and `.rehydrator` properties**

In `src/piighost/integrations/langchain/rag.py`, add to the `PIIGhostRAG` class:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/integrations/langchain/rag.py tests/integrations/langchain/test_rag.py
git commit -m "feat(integrations/langchain): PIIGhostRAG.anonymizer and .rehydrator runnables"
```

---

### Task 4: LangChain — `.retriever` (BaseRetriever)

**Files:**
- Modify: `src/piighost/integrations/langchain/rag.py`
- Modify: `tests/integrations/langchain/test_rag.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/integrations/langchain/test_rag.py`:

```python
def test_retriever_returns_documents(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="client-a")
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works on GDPR compliance contracts")
    asyncio.run(rag.ingest(doc))

    from langchain_core.documents import Document

    docs = asyncio.run(rag.retriever.ainvoke("GDPR compliance"))
    assert isinstance(docs, list)
    assert all(isinstance(d, Document) for d in docs)
    assert len(docs) >= 1


def test_retriever_metadata_includes_project(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="client-a")
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(rag.ingest(doc))

    docs = asyncio.run(rag.retriever.ainvoke("Paris"))
    assert docs[0].metadata["project"] == "client-a"
    assert "doc_id" in docs[0].metadata
    assert "score" in docs[0].metadata


def test_retriever_scoped_to_project(svc, tmp_path):
    rag_a = PIIGhostRAG(svc, project="client-a")
    rag_b = PIIGhostRAG(svc, project="client-b")

    doc = tmp_path / "a.txt"
    doc.write_text("Alice works on GDPR contracts")
    asyncio.run(rag_a.ingest(doc))

    docs_b = asyncio.run(rag_b.retriever.ainvoke("GDPR contracts"))
    assert len(docs_b) == 0
```

- [ ] **Step 2: Run tests — should fail**

```bash
python -m pytest tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: `AttributeError: 'PIIGhostRAG' object has no attribute 'retriever'`.

- [ ] **Step 3: Add `_PIIGhostRetriever` class and `.retriever` property**

In `src/piighost/integrations/langchain/rag.py`, add at module level (before `PIIGhostRAG`):

```python
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
```

Then add the property to `PIIGhostRAG`:

```python
@property
def retriever(self) -> "BaseRetriever":
    retriever_cls = _build_retriever_class()
    return retriever_cls(svc=self._svc, project=self._project)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: 9 PASSED (3 original + 3 Task 3 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/piighost/integrations/langchain/rag.py tests/integrations/langchain/test_rag.py
git commit -m "feat(integrations/langchain): PIIGhostRAG.retriever as BaseRetriever"
```

---

### Task 5: LangChain — `.query(llm)` full flow + `.as_chain()`

**Files:**
- Modify: `src/piighost/integrations/langchain/rag.py`
- Modify: `tests/integrations/langchain/test_rag.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/integrations/langchain/test_rag.py`:

```python
def test_query_without_llm_returns_rehydrated_context(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="client-a")
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris on GDPR compliance")
    asyncio.run(rag.ingest(doc))

    answer = asyncio.run(rag.query("GDPR compliance"))
    # No LLM: raw rehydrated context. Must contain real PII.
    assert "Alice" in answer or "Paris" in answer


def test_query_with_fake_llm(svc, tmp_path):
    pytest.importorskip("langchain_core")
    from langchain_core.language_models import FakeListChatModel

    rag = PIIGhostRAG(svc, project="client-a")
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris on GDPR compliance contracts")
    asyncio.run(rag.ingest(doc))

    # Fake LLM returns anonymized tokens that can be rehydrated
    anon = asyncio.run(rag.anonymizer.ainvoke("Alice works in Paris"))
    fake_answer = f"According to the context, {anon['entities'][0]['token']} works on contracts."
    llm = FakeListChatModel(responses=[fake_answer])

    answer = asyncio.run(rag.query("What does Alice do?", llm=llm))
    # Token should be rehydrated back to "Alice"
    assert "Alice" in answer


def test_as_chain_returns_runnable(svc):
    pytest.importorskip("langchain_core")
    from langchain_core.language_models import FakeListChatModel
    from langchain_core.runnables import Runnable

    rag = PIIGhostRAG(svc, project="client-a")
    llm = FakeListChatModel(responses=["anonymized response"])
    chain = rag.as_chain(llm)
    assert isinstance(chain, Runnable)
```

- [ ] **Step 2: Run tests — should fail**

```bash
python -m pytest tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: `AttributeError: 'PIIGhostRAG' object has no attribute 'query'` (or `as_chain`).

- [ ] **Step 3: Add `.query()` and `.as_chain()` + prompt template**

In `src/piighost/integrations/langchain/rag.py`, add module-level constant:

```python
_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question based on the provided context.\n"
    "The context and question contain opaque tokens of the form <LABEL:hash> (e.g., <PERSON:abc123>).\n"
    "Preserve these tokens EXACTLY in your answer — do not expand, explain, or replace them.\n"
    "If the context does not contain enough information, say \"I don't know.\""
)


def _build_prompt(*, context: str, question: str) -> list:
    from langchain_core.messages import HumanMessage, SystemMessage

    return [
        SystemMessage(content=_DEFAULT_SYSTEM_PROMPT),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}"),
    ]
```

Add the `query` and `as_chain` methods to `PIIGhostRAG`:

```python
async def query(
    self,
    text: str,
    *,
    k: int = 5,
    llm: "BaseLanguageModel | None" = None,
    prompt: Any | None = None,
) -> str:
    anon = await self._svc.anonymize(text, project=self._project)
    result = await self._svc.query(anon.anonymized, project=self._project, k=k)
    context = "\n\n".join(hit.chunk for hit in result.hits)

    if llm is None:
        rehydrated = await self._svc.rehydrate(
            context, project=self._project, strict=False
        )
        return rehydrated.text

    if prompt is not None:
        messages = prompt.format_messages(context=context, question=anon.anonymized)
    else:
        messages = _build_prompt(context=context, question=anon.anonymized)

    raw_answer = await llm.ainvoke(messages)
    answer_text = raw_answer.content if hasattr(raw_answer, "content") else str(raw_answer)
    rehydrated = await self._svc.rehydrate(
        answer_text, project=self._project, strict=False
    )
    return rehydrated.text


def as_chain(
    self,
    llm: "BaseLanguageModel",
    *,
    prompt: Any | None = None,
) -> "Runnable[str, str]":
    from langchain_core.runnables import RunnableLambda

    async def _run(question: str) -> str:
        return await self.query(question, llm=llm, prompt=prompt)

    return RunnableLambda(_run)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/integrations/langchain/test_rag.py -v -p no:randomly
```

Expected: 12 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/integrations/langchain/rag.py tests/integrations/langchain/test_rag.py
git commit -m "feat(integrations/langchain): PIIGhostRAG.query() and as_chain()"
```

---

### Task 6: Haystack — `PIIGhostRetriever` component

**Files:**
- Create: `src/piighost/integrations/haystack/rag.py`
- Modify: `src/piighost/integrations/haystack/__init__.py`
- Create: `tests/integrations/haystack/test_rag_pipeline.py`

- [ ] **Step 1: Write failing test**

Create `tests/integrations/haystack/test_rag_pipeline.py`:

```python
import asyncio

import pytest

pytest.importorskip("haystack")

from piighost.integrations.haystack.rag import PIIGhostRetriever
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


def test_retriever_construction(svc):
    retriever = PIIGhostRetriever(svc, project="client-a", top_k=5)
    assert retriever is not None


def test_retriever_returns_documents(svc, tmp_path):
    from haystack.dataclasses import Document

    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works on GDPR compliance contracts")
    asyncio.run(svc.index_path(doc, project="client-a"))

    retriever = PIIGhostRetriever(svc, project="client-a", top_k=5)
    result = retriever.run(query="GDPR compliance")
    assert "documents" in result
    assert isinstance(result["documents"], list)
    assert all(isinstance(d, Document) for d in result["documents"])
    assert len(result["documents"]) >= 1


def test_retriever_async_equivalent_to_sync(svc, tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(doc, project="client-a"))

    retriever = PIIGhostRetriever(svc, project="client-a", top_k=3)
    sync_result = retriever.run(query="Paris")
    async_result = asyncio.run(retriever.run_async(query="Paris"))
    assert len(sync_result["documents"]) == len(async_result["documents"])


def test_retriever_metadata_includes_project(svc, tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(doc, project="client-a"))

    retriever = PIIGhostRetriever(svc, project="client-a")
    docs = retriever.run(query="Paris")["documents"]
    assert docs[0].meta["project"] == "client-a"
    assert "doc_id" in docs[0].meta
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
python -m pytest tests/integrations/haystack/test_rag_pipeline.py -v -p no:randomly
```

Expected: `ModuleNotFoundError: No module named 'piighost.integrations.haystack.rag'`.

- [ ] **Step 3: Create `src/piighost/integrations/haystack/rag.py`**

```python
"""Haystack RAG wrapper: PIIGhostRetriever component + pipeline factory."""

from __future__ import annotations

from typing import Any

from haystack import Pipeline, component
from haystack.dataclasses import Document

from piighost.integrations.haystack._base import run_coroutine_sync
from piighost.service.core import PIIGhostService


@component
class PIIGhostRetriever:
    """Haystack retriever wrapping :meth:`PIIGhostService.query`."""

    def __init__(
        self,
        svc: PIIGhostService,
        *,
        project: str = "default",
        top_k: int = 5,
    ) -> None:
        self._svc = svc
        self._project = project
        self._top_k = top_k

    @component.output_types(documents=list[Document])
    def run(self, query: str, top_k: int | None = None) -> dict:
        return run_coroutine_sync(self._arun(query, top_k=top_k))

    @component.output_types(documents=list[Document])
    async def run_async(self, query: str, top_k: int | None = None) -> dict:
        return await self._arun(query, top_k=top_k)

    async def _arun(self, query: str, top_k: int | None) -> dict:
        k = top_k if top_k is not None else self._top_k
        result = await self._svc.query(query, project=self._project, k=k)
        docs = [
            Document(
                content=hit.chunk,
                meta={
                    "doc_id": hit.doc_id,
                    "file_path": hit.file_path,
                    "score": hit.score,
                    "rank": hit.rank,
                    "project": self._project,
                },
            )
            for hit in result.hits
        ]
        return {"documents": docs}
```

- [ ] **Step 4: Update `src/piighost/integrations/haystack/__init__.py`**

Append:

```python
from piighost.integrations.haystack.rag import PIIGhostRetriever  # noqa: F401
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/integrations/haystack/test_rag_pipeline.py -v -p no:randomly
```

Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/integrations/haystack/rag.py \
        src/piighost/integrations/haystack/__init__.py \
        tests/integrations/haystack/test_rag_pipeline.py
git commit -m "feat(integrations/haystack): PIIGhostRetriever component"
```

---

### Task 7: Haystack — `build_piighost_rag` factory

**Files:**
- Modify: `src/piighost/integrations/haystack/rag.py`
- Modify: `src/piighost/integrations/haystack/__init__.py`
- Modify: `tests/integrations/haystack/test_rag_pipeline.py`

**Note on existing Haystack components**: `PIIGhostQueryAnonymizer` and `PIIGhostRehydrator` already exist in `src/piighost/integrations/haystack/documents.py`. They currently use `ThreadAnonymizationPipeline` (lower level) rather than `PIIGhostService`. Sprint 6a wires a **new** factory that uses them as-is — no changes to those components. The factory accepts a `svc: PIIGhostService` and passes `project` through the retriever only. For query anonymization, the factory uses a small local anonymizer component that delegates to the service.

- [ ] **Step 1: Write failing test**

Append to `tests/integrations/haystack/test_rag_pipeline.py`:

```python
def test_build_pipeline_without_llm(svc):
    from haystack import Pipeline
    from piighost.integrations.haystack.rag import build_piighost_rag

    pipeline = build_piighost_rag(svc, project="client-a")
    assert isinstance(pipeline, Pipeline)
    # Components that must always be present
    names = set(pipeline.graph.nodes)
    assert "query_anonymizer" in names
    assert "retriever" in names
    assert "prompt_builder" in names
    assert "rehydrator" in names


def test_build_pipeline_with_llm(svc):
    from haystack import Pipeline
    from piighost.integrations.haystack.rag import build_piighost_rag

    # Any placeholder component works — we just assert wiring, not execution
    class _FakeGenerator:
        @component.output_types(replies=list[str])
        def run(self, prompt: str) -> dict:
            return {"replies": [prompt]}

    # @component decorator mutates class — wrap in a component
    pipeline = build_piighost_rag(svc, project="client-a", llm_generator=_FakeGenerator())
    assert "llm" in pipeline.graph.nodes


def test_pipeline_runs_without_llm(svc, tmp_path):
    from piighost.integrations.haystack.rag import build_piighost_rag

    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris on GDPR compliance")
    asyncio.run(svc.index_path(doc, project="client-a"))

    pipeline = build_piighost_rag(svc, project="client-a")
    # Without an LLM, the pipeline produces the prompt. Run up to prompt_builder.
    output = pipeline.run({"query_anonymizer": {"text": "GDPR compliance"}})
    assert "prompt_builder" in output
```

Also add at the top of the file (after existing imports):

```python
from haystack import component
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/integrations/haystack/test_rag_pipeline.py -v -p no:randomly
```

Expected: `ImportError: cannot import name 'build_piighost_rag'`.

- [ ] **Step 3: Add the factory function + service-backed anonymizer to `rag.py`**

Read `src/piighost/integrations/haystack/rag.py` (from Task 6). Append:

```python
_HAYSTACK_PROMPT_TEMPLATE = """You are a helpful assistant. Answer based on the provided context.
Both the context and question contain opaque tokens like <LABEL:hash>. Preserve them exactly.

Context:
{% for doc in documents %}
{{ doc.content }}
{% endfor %}

Question: {{ question }}
"""


@component
class _ServiceQueryAnonymizer:
    """Anonymize a query via PIIGhostService (project-scoped)."""

    def __init__(self, svc: PIIGhostService, *, project: str = "default") -> None:
        self._svc = svc
        self._project = project

    @component.output_types(query=str)
    def run(self, text: str) -> dict:
        return run_coroutine_sync(self._arun(text))

    @component.output_types(query=str)
    async def run_async(self, text: str) -> dict:
        return await self._arun(text)

    async def _arun(self, text: str) -> dict:
        result = await self._svc.anonymize(text, project=self._project)
        return {"query": result.anonymized}


@component
class _ServiceRehydrator:
    """Rehydrate text via PIIGhostService (project-scoped)."""

    def __init__(self, svc: PIIGhostService, *, project: str = "default") -> None:
        self._svc = svc
        self._project = project

    @component.output_types(text=str)
    def run(self, text: str) -> dict:
        return run_coroutine_sync(self._arun(text))

    @component.output_types(text=str)
    async def run_async(self, text: str) -> dict:
        return await self._arun(text)

    async def _arun(self, text: str) -> dict:
        result = await self._svc.rehydrate(text, project=self._project, strict=False)
        return {"text": result.text}


def build_piighost_rag(
    svc: PIIGhostService,
    *,
    project: str = "default",
    llm_generator: Any | None = None,
    top_k: int = 5,
) -> Pipeline:
    """Build a pre-wired Haystack :class:`Pipeline` for PII-safe RAG.

    Components and connections (with LLM):

        query_anonymizer → retriever → prompt_builder → llm → rehydrator

    Without an LLM the pipeline stops at ``prompt_builder``. This lets tests
    assert wiring without exercising an LLM.
    """
    from haystack.components.builders import PromptBuilder

    pipeline = Pipeline()
    pipeline.add_component(
        "query_anonymizer", _ServiceQueryAnonymizer(svc, project=project)
    )
    pipeline.add_component(
        "retriever", PIIGhostRetriever(svc, project=project, top_k=top_k)
    )
    pipeline.add_component(
        "prompt_builder", PromptBuilder(template=_HAYSTACK_PROMPT_TEMPLATE)
    )
    pipeline.add_component(
        "rehydrator", _ServiceRehydrator(svc, project=project)
    )
    if llm_generator is not None:
        pipeline.add_component("llm", llm_generator)

    pipeline.connect("query_anonymizer.query", "retriever.query")
    pipeline.connect("query_anonymizer.query", "prompt_builder.question")
    pipeline.connect("retriever.documents", "prompt_builder.documents")
    if llm_generator is not None:
        pipeline.connect("prompt_builder.prompt", "llm.prompt")
        pipeline.connect("llm.replies", "rehydrator.text")

    return pipeline
```

- [ ] **Step 4: Update `src/piighost/integrations/haystack/__init__.py`**

Append:

```python
from piighost.integrations.haystack.rag import build_piighost_rag  # noqa: F401
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/integrations/haystack/test_rag_pipeline.py -v -p no:randomly
```

Expected: 7 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/integrations/haystack/rag.py \
        src/piighost/integrations/haystack/__init__.py \
        tests/integrations/haystack/test_rag_pipeline.py
git commit -m "feat(integrations/haystack): build_piighost_rag pipeline factory"
```

---

### Task 8: E2E LangChain RAG roundtrip with PII-zero-leak check

**Files:**
- Create: `tests/e2e/test_langchain_rag_roundtrip.py`

- [ ] **Step 1: Write the test**

Create `tests/e2e/test_langchain_rag_roundtrip.py`:

```python
"""E2E: LangChain PIIGhostRAG — ingest, query with fake LLM, verify no PII leak."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("langchain_core")

from piighost.integrations.langchain.rag import PIIGhostRAG
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


class _RecordingFakeLLM:
    """Minimal LangChain-compatible LLM that records every input."""

    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def ainvoke(self, messages, config=None, **kwargs):
        from langchain_core.messages import AIMessage

        serialized = "\n".join(
            getattr(m, "content", str(m)) for m in messages
        )
        self.inputs.append(serialized)
        return AIMessage(content="(fake response)")

    def invoke(self, messages, config=None, **kwargs):
        return asyncio.run(self.ainvoke(messages, config, **kwargs))


def test_langchain_rag_roundtrip(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="client-a")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "a.txt").write_text("Alice works in Paris on GDPR compliance contracts.")
    (docs_dir / "b.txt").write_text("Paris is the location of the data processing agreement.")

    report = asyncio.run(rag.ingest(docs_dir))
    assert report.indexed >= 1

    llm = _RecordingFakeLLM()
    answer = asyncio.run(rag.query("Where does Alice work?", llm=llm))
    assert isinstance(answer, str)


def test_langchain_rag_no_pii_leak_to_llm(svc, tmp_path):
    rag = PIIGhostRAG(svc, project="client-a")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "a.txt").write_text("Alice works in Paris on GDPR compliance contracts.")

    asyncio.run(rag.ingest(docs_dir))

    llm = _RecordingFakeLLM()
    asyncio.run(rag.query("Alice in Paris?", llm=llm))

    # CRITICAL: Raw PII must never appear in what we sent to the LLM
    assert llm.inputs, "fake LLM received no input — test didn't exercise the path"
    for captured in llm.inputs:
        assert "Alice" not in captured, f"raw PII 'Alice' leaked to LLM input: {captured!r}"
        assert "Paris" not in captured, f"raw PII 'Paris' leaked to LLM input: {captured!r}"
```

- [ ] **Step 2: Run the tests**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
python -m pytest tests/e2e/test_langchain_rag_roundtrip.py -v -p no:randomly
```

Expected: 2 PASSED.

- [ ] **Step 3: Run full suite — no regressions**

```bash
python -m pytest tests/unit/ tests/e2e/ tests/integrations/langchain/ -q -p no:randomly 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_langchain_rag_roundtrip.py
git commit -m "test(e2e): LangChain RAG roundtrip + PII-zero-leak to LLM"
```

---

### Task 9: E2E Haystack RAG roundtrip with PII-zero-leak check

**Files:**
- Create: `tests/e2e/test_haystack_rag_roundtrip.py`

- [ ] **Step 1: Write the test**

Create `tests/e2e/test_haystack_rag_roundtrip.py`:

```python
"""E2E: Haystack build_piighost_rag — pipeline ingest + run with fake generator, no PII leak."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("haystack")

from haystack import component

from piighost.integrations.haystack.rag import build_piighost_rag
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


@component
class _RecordingFakeGenerator:
    """Haystack Generator that records every prompt it receives."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    @component.output_types(replies=list[str])
    def run(self, prompt: str) -> dict:
        self.prompts.append(prompt)
        # Return a fake "anonymized" reply — in a real test this could be a
        # token from the context. For zero-leak we only care about what went IN.
        return {"replies": ["(fake reply)"]}


def test_haystack_rag_roundtrip(svc, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works in Paris on GDPR compliance contracts.")

    asyncio.run(svc.index_path(docs, project="client-a"))

    gen = _RecordingFakeGenerator()
    pipeline = build_piighost_rag(svc, project="client-a", llm_generator=gen)
    output = pipeline.run({"query_anonymizer": {"text": "Where does Alice work?"}})
    assert "rehydrator" in output


def test_haystack_rag_no_pii_leak_to_generator(svc, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Alice works in Paris on GDPR compliance contracts.")

    asyncio.run(svc.index_path(docs, project="client-a"))

    gen = _RecordingFakeGenerator()
    pipeline = build_piighost_rag(svc, project="client-a", llm_generator=gen)
    pipeline.run({"query_anonymizer": {"text": "Alice in Paris?"}})

    assert gen.prompts, "fake generator received no prompt — test didn't exercise the path"
    for prompt in gen.prompts:
        assert "Alice" not in prompt, f"raw PII 'Alice' leaked to generator: {prompt!r}"
        assert "Paris" not in prompt, f"raw PII 'Paris' leaked to generator: {prompt!r}"
```

- [ ] **Step 2: Run the tests**

```bash
python -m pytest tests/e2e/test_haystack_rag_roundtrip.py -v -p no:randomly
```

Expected: 2 PASSED.

- [ ] **Step 3: Run full suite — no regressions**

```bash
python -m pytest tests/unit/ tests/e2e/ tests/integrations/ -q -p no:randomly 2>&1 | tail -15
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_haystack_rag_roundtrip.py
git commit -m "test(e2e): Haystack RAG roundtrip + PII-zero-leak to generator"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Task |
|------------------|------|
| Fix `test_hybrid_retrieval.py` import | Task 1 |
| `PIIGhostRAG` class construction + `.ingest()` | Task 2 |
| `PIIGhostRAG.anonymizer` and `.rehydrator` runnables | Task 3 |
| `PIIGhostRAG.retriever` as `BaseRetriever` | Task 4 |
| `PIIGhostRAG.query()` full flow | Task 5 |
| `PIIGhostRAG.as_chain()` | Task 5 |
| Default system prompt preserving tokens | Task 5 |
| `PIIGhostRetriever` Haystack component | Task 6 |
| `build_piighost_rag` factory | Task 7 |
| E2E LangChain roundtrip + zero-leak | Task 8 |
| E2E Haystack roundtrip + zero-leak | Task 9 |
| Backward compat: existing integrations unchanged | Design choice — no tasks touch existing transformers/middleware/documents modules |

### Placeholder scan

- No "TBD" markers.
- All code blocks complete and copy-pasteable.
- Expected test outputs specified at each verification step.
- Commit messages provided for each task.

### Type consistency

- `PIIGhostRAG(svc, project="...")` constructor signature consistent across Tasks 2-5.
- `svc.query(query, project=..., k=...)` call signature consistent with Sprint 5's multiplexer.
- `svc.anonymize(text, project=...)` consistent.
- `svc.rehydrate(text, project=..., strict=False)` consistent.
- `svc.index_path(path, recursive=..., force=..., project=...)` consistent.
- `IndexReport.project` field referenced in Task 2 test — this field exists after Sprint 5 Task 6.
- `Document` types: LangChain uses `langchain_core.documents.Document`; Haystack uses `haystack.dataclasses.Document`. Never mixed.
- All property names (`anonymizer`, `retriever`, `rehydrator`) consistent between Tasks 3, 4, 5.
- `PIIGhostRetriever(svc, project=..., top_k=...)` consistent with `build_piighost_rag` wiring in Task 7.

All checks pass.
