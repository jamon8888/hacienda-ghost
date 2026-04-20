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
