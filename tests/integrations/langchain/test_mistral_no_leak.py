"""Proof: when wired correctly, the Mistral embedder never sees raw PII."""

import os

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langchain_mistralai")
pytest.importorskip("httpx")

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

import httpx  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
    PIIGhostQueryAnonymizer,
)


async def test_no_raw_pii_in_outbound_request_body(pipeline, monkeypatch) -> None:
    from langchain_mistralai import MistralAIEmbeddings

    # monkeypatch so MISTRAL_API_KEY doesn't leak into test_lancedb_roundtrip[mistral]
    # (which uses `os.getenv("MISTRAL_API_KEY")` to decide whether to skip).
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

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
    # base_url is required: MistralAIEmbeddings issues requests against the
    # relative path "/embeddings"; without a base_url httpx raises
    # "unknown url type: '/embeddings'".
    base_url = "https://api.mistral.ai/v1/"
    client = httpx.Client(transport=transport, base_url=base_url)
    async_client = httpx.AsyncClient(transport=transport, base_url=base_url)

    embeddings = MistralAIEmbeddings(
        model="mistral-embed", client=client, async_client=async_client
    )

    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    raw = [Document(page_content="Alice visited Paris", metadata={"source": "a"})]
    anonymized = await anonymizer.atransform_documents(raw)

    embeddings.embed_documents([d.page_content for d in anonymized])

    query_anon = PIIGhostQueryAnonymizer(pipeline=pipeline)
    qresult = await query_anon.ainvoke("Where did Alice go?")
    embeddings.embed_query(qresult["query"])

    assert captured, "mock transport should have captured at least one request"
    for body in captured:
        text = body.decode("utf-8", errors="replace")
        # The stub detector (see conftest) only flags "Alice" as PERSON. That's
        # the PII this test verifies never leaves the process; "Paris" stays as
        # plain text by design (see test_pipeline_wiring for the explicit
        # coverage of that behaviour).
        assert "Alice" not in text, "raw PII leaked to Mistral embedder"
