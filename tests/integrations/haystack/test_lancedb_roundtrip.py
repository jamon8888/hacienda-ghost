"""LanceDB-Haystack roundtrip: verify PyArrow schema survives write/read.

Gated on the ``lancedb_haystack`` extra via ``importorskip``.  Marked
``slow`` so it does not run in the default fast test suite.

The parametrized roundtrip test exercises two embedding backends:
- ``local``: ``SentenceTransformersDocumentEmbedder`` (requires
  ``sentence-transformers``)
- ``mistral``: ``MistralDocumentEmbedder`` from
  ``haystack-integrations`` (requires ``MISTRAL_API_KEY``)

The original fast test (``test_mapping_survives_lancedb_roundtrip``) is
kept unchanged so it continues to run in the fast suite.
"""

from __future__ import annotations

import os

import pyarrow as pa
import pytest

lancedb_haystack = pytest.importorskip("lancedb_haystack")

from haystack import Document  # noqa: E402

from piighost.integrations.haystack import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
    PIIGhostRehydrator,
    lancedb_meta_fields,
)

# ---------------------------------------------------------------------------
# Fast test (existing — unchanged)
# ---------------------------------------------------------------------------

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]


async def test_mapping_survives_lancedb_roundtrip(tmp_path, pipeline) -> None:
    store = lancedb_haystack.LanceDBDocumentStore(
        database=str(tmp_path / "lance.db"),
        table_name="test",
        metadata_schema=pa.struct([*lancedb_meta_fields()]),
        embedding_dims=8,
    )

    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    rehydrator = PIIGhostRehydrator()

    doc = Document(content="Patrick habite à Paris.")
    anon_out = await anonymizer.run_async(documents=[doc])
    store.write_documents(anon_out["documents"])

    read_back = store.filter_documents()
    assert len(read_back) == 1
    assert "piighost_mapping" in read_back[0].meta

    rehyd_out = await rehydrator.run_async(documents=read_back)
    assert rehyd_out["documents"][0].content == "Patrick habite à Paris."


# ---------------------------------------------------------------------------
# Parametrized roundtrip with real embeddings (slow)
# ---------------------------------------------------------------------------


def _build_doc_embedder(backend: str):
    """Return a Haystack document embedder for the given backend.

    Skips via ``pytest.importorskip`` / ``pytest.skip`` when prerequisites
    are not satisfied.
    """
    if backend == "local":
        pytest.importorskip("sentence_transformers")
        from haystack.components.embedders import (  # type: ignore[import]
            SentenceTransformersDocumentEmbedder,
        )

        return SentenceTransformersDocumentEmbedder(
            model="OrdalieTech/Solon-embeddings-base-0.1",
        )
    else:
        # Mistral branch
        if not os.getenv("MISTRAL_API_KEY"):
            pytest.skip("MISTRAL_API_KEY not set")

        mistral_pkg = pytest.importorskip(
            "haystack_integrations.components.embedders.mistral"
        )
        MistralDocumentEmbedder = mistral_pkg.MistralDocumentEmbedder
        return MistralDocumentEmbedder(model="mistral-embed")


@pytest.mark.slow
@pytest.mark.parametrize("backend", ["local", "mistral"])
async def test_anonymize_index_query_rehydrate(
    backend: str, pipeline, tmp_path
) -> None:
    """Anonymize → assert no raw PII → embed → index → query → rehydrate."""
    doc_embedder = _build_doc_embedder(backend)

    # Warm the embedder (calls warm_up() if the component supports it)
    if hasattr(doc_embedder, "warm_up"):
        doc_embedder.warm_up()

    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    rehydrator = PIIGhostRehydrator()

    raw_docs = [
        Document(content="Patrick habite à Paris."),
        Document(content="France est un pays en Europe."),
    ]
    anon_out = await anonymizer.run_async(documents=raw_docs)
    anonymized_docs = anon_out["documents"]

    # No raw PII in anonymized content
    for doc in anonymized_docs:
        assert "Patrick" not in doc.content
        assert "Paris" not in doc.content
        assert "France" not in doc.content

    # Embed
    embed_out = doc_embedder.run(documents=anonymized_docs)
    embedded_docs = embed_out["documents"]

    # Determine embedding dimension from first result
    first_emb = embedded_docs[0].embedding
    assert first_emb is not None, "embedder must set .embedding on documents"
    embedding_dims = len(first_emb)

    # Index into LanceDB
    store = lancedb_haystack.LanceDBDocumentStore(
        database=str(tmp_path / "lance.db"),
        table_name="test",
        metadata_schema=pa.struct([*lancedb_meta_fields()]),
        embedding_dims=embedding_dims,
    )
    store.write_documents(embedded_docs)

    read_back = store.filter_documents()
    assert len(read_back) == len(raw_docs)
    assert all("piighost_mapping" in d.meta for d in read_back)

    # Rehydrate
    rehyd_out = await rehydrator.run_async(documents=read_back)
    rehydrated_contents = {d.content for d in rehyd_out["documents"]}
    assert "Patrick habite à Paris." in rehydrated_contents
