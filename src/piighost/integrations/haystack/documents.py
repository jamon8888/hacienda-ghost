"""Haystack components for the PIIGhost document pipeline."""

import json
import logging
from typing import Any

from haystack import Document, component

from piighost.integrations.haystack._base import run_coroutine_sync
from piighost.models import Entity
from piighost.pipeline.thread import ThreadAnonymizationPipeline
from piighost.placeholder import AnyPlaceholderFactory, CounterPlaceholderFactory

logger = logging.getLogger(__name__)


def _serialize_mapping(
    entities: list[Entity],
    ph_factory: AnyPlaceholderFactory,
) -> str:
    """Serialize the (token → original) mapping as a JSON list string.

    Each item has ``token``, ``original``, and ``label`` so the Rehydrator
    can rebuild the token → original map without re-running the factory.
    """
    tokens = ph_factory.create(entities)
    items: list[dict[str, str]] = []
    for entity, token in tokens.items():
        for detection in entity.detections:
            items.append(
                {
                    "token": token,
                    "original": detection.text,
                    "label": entity.label,
                }
            )
    return json.dumps(items)


def _build_profile(entities: list[Entity]) -> dict[str, Any]:
    """Compact booleans-and-counts profile for filter-friendly meta."""
    labels = sorted({e.label for e in entities})
    return {
        "has_person": any(e.label == "PERSON" for e in entities),
        "has_email": any("EMAIL" in e.label.upper() for e in entities),
        "has_location": any(e.label == "LOCATION" for e in entities),
        "n_entities": len(entities),
        "labels": labels,
    }


@component
class PIIGhostDocumentAnonymizer:
    """Anonymize Haystack Documents in place, storing the mapping in meta.

    Uses each document's ``id`` as the pipeline ``thread_id`` so that
    mapping and cache are scoped per document.  The ``content`` is
    replaced with anonymized text; the mapping is stored as a JSON
    string under ``meta[meta_key]`` (default ``"piighost_mapping"``).

    Args:
        pipeline: A configured ``ThreadAnonymizationPipeline``.
        populate_profile: If ``True``, also writes a JSON profile summary
            to ``meta["piighost_profile"]``.
        meta_key: Meta dict key for the serialized mapping.
        strict: If ``True``, re-raise errors from detection. Default is
            lenient (log ERROR, leave content unchanged, write
            ``meta["piighost_error"]``).
        allow_non_stable_tokens: Escape hatch for using
            ``CounterPlaceholderFactory``.  Default ``False`` rejects it
            at construction time with a clear error.
    """

    def __init__(
        self,
        pipeline: ThreadAnonymizationPipeline,
        populate_profile: bool = False,
        meta_key: str = "piighost_mapping",
        strict: bool = False,
        allow_non_stable_tokens: bool = False,
    ) -> None:
        if (
            isinstance(pipeline.ph_factory, CounterPlaceholderFactory)
            and not allow_non_stable_tokens
        ):
            raise ValueError(
                "CounterPlaceholderFactory is not recommended for document "
                "pipelines because its tokens are not stable across documents "
                "or queries. Use HashPlaceholderFactory instead, or pass "
                "allow_non_stable_tokens=True if you know what you're doing."
            )
        self._pipeline = pipeline
        self._populate_profile = populate_profile
        self._meta_key = meta_key
        self._strict = strict

    @component.output_types(documents=list[Document])
    async def run_async(self, documents: list[Document]) -> dict[str, list[Document]]:
        for doc in documents:
            await self._process(doc)
        return {"documents": documents}

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict[str, list[Document]]:
        return run_coroutine_sync(self.run_async(documents=documents))

    async def _process(self, doc: Document) -> None:
        content = doc.content
        if content is None or not content.strip():
            logger.warning("Skipping doc %s: empty content", doc.id)
            return

        thread_id = doc.id if doc.id else "default"

        try:
            anonymized, entities = await self._pipeline.anonymize(
                content, thread_id=thread_id
            )
        except Exception as exc:
            if self._strict:
                raise
            logger.error("anonymization failed for doc %s: %s", doc.id, exc)
            doc.meta["piighost_error"] = f"detection_failed:{type(exc).__name__}"
            return

        doc.content = anonymized
        doc.meta[self._meta_key] = _serialize_mapping(
            entities, self._pipeline.ph_factory
        )
        if self._populate_profile:
            doc.meta["piighost_profile"] = json.dumps(_build_profile(entities))


@component
class PIIGhostQueryAnonymizer:
    """Anonymize a query string to match indexed anonymized content.

    Uses the same ``ThreadAnonymizationPipeline`` as the document
    anonymizer. Because ``HashPlaceholderFactory`` is deterministic,
    the same entity produces the same token in a query as in an
    indexed document — so anonymized queries retrieve anonymized docs
    correctly.

    **Strict by default:** any error raises. Silent pass-through would
    leak PII into the downstream embedder and LLM.

    Args:
        pipeline: A configured ``ThreadAnonymizationPipeline``.
    """

    def __init__(self, pipeline: ThreadAnonymizationPipeline) -> None:
        self._pipeline = pipeline

    @component.output_types(query=str, entities=list[Entity])
    async def run_async(self, query: str, scope: str = "query") -> dict[str, Any]:
        anonymized, entities = await self._pipeline.anonymize(query, thread_id=scope)
        return {"query": anonymized, "entities": entities}

    @component.output_types(query=str, entities=list[Entity])
    def run(self, query: str, scope: str = "query") -> dict[str, Any]:
        return run_coroutine_sync(self.run_async(query=query, scope=scope))
