"""Proof: when wired correctly, the Mistral embedder never sees raw PII.

Gated on ``haystack`` and ``haystack_integrations`` extras.  Uses
``httpx.MockTransport`` injected via ``http_client_kwargs`` into the
Mistral embedder so every outbound request body is captured and inspected.

Marked ``slow`` — skips cleanly when extras are absent.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("haystack")
mistral_mod = pytest.importorskip("haystack_integrations.components.embedders.mistral")
pytest.importorskip("httpx")

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

import httpx  # noqa: E402
from haystack import Document  # noqa: E402

from piighost.integrations.haystack import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
    PIIGhostQueryAnonymizer,
)


async def test_no_raw_pii_in_outbound_request_body(pipeline) -> None:
    """Assert that 'Alice' and 'Paris' never appear in requests to Mistral."""
    MistralDocumentEmbedder = mistral_mod.MistralDocumentEmbedder
    MistralTextEmbedder = mistral_mod.MistralTextEmbedder

    captured: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(bytes(request.content))
        import json as _json

        body = _json.loads(request.content.decode("utf-8")) if request.content else {}
        inputs = body.get("input", [])
        n = len(inputs) if isinstance(inputs, list) else 1
        return httpx.Response(
            200,
            json={
                "id": "embd-test",
                "object": "list",
                "model": "mistral-embed",
                "data": [
                    {"object": "embedding", "index": i, "embedding": [0.0] * 1024}
                    for i in range(n)
                ],
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
            },
        )

    transport = httpx.MockTransport(handler)

    os.environ.setdefault("MISTRAL_API_KEY", "test-key")

    # Inject the mock transport via http_client_kwargs so all outbound HTTP
    # requests (both sync and async) go through our handler.
    http_client_kwargs = {"transport": transport}

    # Check if http_client_kwargs is supported (mistral-haystack >= 1.2)
    import inspect

    doc_embedder_sig = inspect.signature(MistralDocumentEmbedder.__init__)
    if "http_client_kwargs" not in doc_embedder_sig.parameters:
        pytest.skip(
            "Cannot inject transport into MistralDocumentEmbedder "
            "(http_client_kwargs not supported in this version); skipping leak-proof test"
        )

    # Anonymize documents first
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    raw_docs = [Document(content="Alice visited Paris")]
    anon_out = await anonymizer.run_async(documents=raw_docs)
    anonymized_docs = anon_out["documents"]

    # Assert no raw PII in the anonymized content before embedding
    for doc in anonymized_docs:
        assert "Alice" not in doc.content
        assert "Paris" not in doc.content

    # Embed documents via Mistral with mock transport
    doc_embedder = MistralDocumentEmbedder(
        model="mistral-embed",
        http_client_kwargs=http_client_kwargs,
    )
    if hasattr(doc_embedder, "warm_up"):
        doc_embedder.warm_up()
    doc_embedder.run(documents=anonymized_docs)

    # Anonymize query and embed it
    query_anon = PIIGhostQueryAnonymizer(pipeline=pipeline)
    q_out = await query_anon.run_async(query="Where did Alice go?")
    anonymized_query = q_out["query"]
    assert "Alice" not in anonymized_query

    text_embedder_sig = inspect.signature(MistralTextEmbedder.__init__)
    if "http_client_kwargs" in text_embedder_sig.parameters:
        text_embedder = MistralTextEmbedder(
            model="mistral-embed",
            http_client_kwargs=http_client_kwargs,
        )
    else:
        text_embedder = MistralTextEmbedder(model="mistral-embed")

    if hasattr(text_embedder, "warm_up"):
        text_embedder.warm_up()
    text_embedder.run(text=anonymized_query)

    # The mock transport must have intercepted at least one request.
    assert captured, "mock transport should have captured at least one request"
    for body in captured:
        text = body.decode("utf-8", errors="replace")
        assert "Alice" not in text, "raw PII 'Alice' leaked to Mistral embedder"
        assert "Paris" not in text, "raw PII 'Paris' leaked to Mistral embedder"
