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

    # Seed project client-b so it exists
    asyncio.run(svc.anonymize("seed", project="client-b"))

    docs_b = asyncio.run(rag_b.retriever.ainvoke("GDPR contracts"))
    assert len(docs_b) == 0


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

    # Fake LLM returns an answer containing a token that can be rehydrated
    anon = asyncio.run(rag.anonymizer.ainvoke("Alice works in Paris"))
    fake_answer = f"According to the context, {anon['entities'][0]['token']} works on contracts."
    llm = FakeListChatModel(responses=[fake_answer])

    answer = asyncio.run(rag.query("What does Alice do?", llm=llm))
    # Token should be rehydrated back to "Alice" (or "Paris")
    assert "Alice" in answer or "Paris" in answer


def test_as_chain_returns_runnable(svc):
    pytest.importorskip("langchain_core")
    from langchain_core.language_models import FakeListChatModel
    from langchain_core.runnables import Runnable

    rag = PIIGhostRAG(svc, project="client-a")
    llm = FakeListChatModel(responses=["anonymized response"])
    chain = rag.as_chain(llm)
    assert isinstance(chain, Runnable)
