"""Hybrid retrieval (BM25 + embedding) recovers exact-name recall on anonymized docs.

Scenario: a corpus contains three documents, only one mentions 'Alain Dupont'.
A query with the same name must rank that document first.  Pure vector search
on anonymized tokens underperforms because ``<PERSON:hash>`` is opaque; BM25
on the same token is exact.  Haystack's ``DocumentJoiner`` with
``reciprocal_rank_fusion`` combines the two legs.

Gated on ``haystack`` (always imported at module level via ``importorskip``) and
``sentence_transformers`` (imported lazily inside the test).  Marked ``slow``.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("haystack")

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

from haystack import AsyncPipeline, Document  # noqa: E402
from haystack.components.joiners.document_joiner import DocumentJoiner  # noqa: E402
from haystack.components.retrievers.in_memory import (  # noqa: E402
    InMemoryBM25Retriever,
    InMemoryEmbeddingRetriever,
)
from haystack.document_stores.in_memory import InMemoryDocumentStore  # noqa: E402

from piighost.anonymizer import Anonymizer  # noqa: E402
from piighost.models import Detection, Span  # noqa: E402
from piighost.pipeline.thread import ThreadAnonymizationPipeline  # noqa: E402
from piighost.placeholder import HashPlaceholderFactory  # noqa: E402
from piighost.integrations.haystack import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)


# ---------------------------------------------------------------------------
# Inline detector for 'Alain Dupont' — conftest only detects 'Patrick'/'Paris'
# ---------------------------------------------------------------------------


class _AlainDetector:
    """Detects 'Alain Dupont' as a single PERSON entity."""

    _NAME = "Alain Dupont"

    async def detect(self, text: str) -> list[Detection]:
        idx = text.find(self._NAME)
        if idx < 0:
            return []
        return [
            Detection(
                text=self._NAME,
                label="PERSON",
                position=Span(start_pos=idx, end_pos=idx + len(self._NAME)),
                confidence=1.0,
            )
        ]


@pytest.fixture
def alain_pipeline() -> ThreadAnonymizationPipeline:
    """Local pipeline that recognises 'Alain Dupont' as a PERSON entity."""
    return ThreadAnonymizationPipeline(
        detector=_AlainDetector(),  # type: ignore[arg-type]
        anonymizer=Anonymizer(HashPlaceholderFactory()),
    )


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------


def _make_embedder():
    """Return a Haystack SentenceTransformers document embedder.

    Skips via ``pytest.importorskip`` when sentence-transformers is absent.
    """
    pytest.importorskip("sentence_transformers")
    from haystack.components.embedders import (  # type: ignore[import]
        SentenceTransformersDocumentEmbedder,
        SentenceTransformersTextEmbedder,
    )

    doc_embedder = SentenceTransformersDocumentEmbedder(
        model="OrdalieTech/Solon-embeddings-base-0.1",
    )
    text_embedder = SentenceTransformersTextEmbedder(
        model="OrdalieTech/Solon-embeddings-base-0.1",
        prefix="query: ",
    )
    return doc_embedder, text_embedder


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_bm25_plus_vector_recovers_exact_name(alain_pipeline) -> None:
    """BM25 + embedding retrieval must surface the Alain Dupont document first."""
    doc_embedder, text_embedder = _make_embedder()

    anonymizer = PIIGhostDocumentAnonymizer(pipeline=alain_pipeline)
    query_anon = PIIGhostQueryAnonymizer(pipeline=alain_pipeline)
    rehydrator = PIIGhostRehydrator()

    raw_docs = [
        Document(
            content="The legal brief mentions Alain Dupont as plaintiff.",
            meta={"source": "case-1"},
        ),
        Document(
            content="Contract law overview: consideration and offer.",
            meta={"source": "doctrine-1"},
        ),
        Document(
            content="Procedural deadlines for civil suits in France.",
            meta={"source": "procedure-1"},
        ),
    ]

    anon_out = await anonymizer.run_async(documents=raw_docs)
    anonymized_docs = anon_out["documents"]

    for doc in anonymized_docs:
        assert "Alain" not in doc.content, "raw PII must not appear in anonymized docs"

    # Confirm token identity before running the ensemble
    # (BM25 only works when document path and query path yield the same token)
    q_out = await query_anon.run_async(
        query="What does the brief say about Alain Dupont?"
    )
    anonymized_query = q_out["query"]

    assert "Alain" not in anonymized_query, "query must be anonymized before retrieval"

    # Use regex to avoid picking up trailing punctuation ("<PERSON:abc123>?"
    # etc.) from whitespace splits.
    match = re.search(r"<PERSON:[0-9a-f]+>", anonymized_query)
    alice_token = match.group(0) if match else None
    assert alice_token is not None, "query should contain an anonymized PERSON token"
    assert any(alice_token in doc.content for doc in anonymized_docs), (
        "HashPlaceholderFactory must produce the same token for document and query paths"
    )

    # --- Warm up embedders ---
    doc_embedder.warm_up()
    text_embedder.warm_up()

    # --- Embed documents ---
    embed_out = doc_embedder.run(documents=anonymized_docs)
    embedded_docs = embed_out["documents"]

    # --- Build document store and write documents ---
    store = InMemoryDocumentStore()
    store.write_documents(embedded_docs)

    # --- Build hybrid pipeline: BM25 + embedding, joined via RRF ---
    # AsyncPipeline + run_async is required because PIIGhostRehydrator
    # refuses sync .run() from inside a running event loop (the test is
    # async). See piighost.integrations.haystack._base.
    retrieval_pipe = AsyncPipeline()
    retrieval_pipe.add_component("bm25", InMemoryBM25Retriever(document_store=store))
    retrieval_pipe.add_component("text_embedder", text_embedder)
    retrieval_pipe.add_component(
        "embedding_retriever", InMemoryEmbeddingRetriever(document_store=store)
    )
    retrieval_pipe.add_component(
        "joiner",
        DocumentJoiner(join_mode="reciprocal_rank_fusion"),
    )
    retrieval_pipe.add_component("rehydrator", rehydrator)

    retrieval_pipe.connect(
        "text_embedder.embedding", "embedding_retriever.query_embedding"
    )
    retrieval_pipe.connect("bm25.documents", "joiner.documents")
    retrieval_pipe.connect("embedding_retriever.documents", "joiner.documents")
    retrieval_pipe.connect("joiner.documents", "rehydrator.documents")

    result = await retrieval_pipe.run_async(
        {
            "bm25": {"query": anonymized_query, "top_k": 3},
            "text_embedder": {"text": anonymized_query},
            "embedding_retriever": {"top_k": 3},
        }
    )

    rehydrated = result["rehydrator"]["documents"]
    assert rehydrated, "hybrid pipeline should return at least one document"

    top = rehydrated[0]
    assert "Alain Dupont" in top.content, (
        "hybrid retrieval must surface the exact-name document first"
    )
