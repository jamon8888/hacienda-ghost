"""Tests for ThreadAnonymizationPipeline.anonymize_batch()."""
import pytest
from piighost.anonymizer import Anonymizer
from piighost.detector import ExactMatchDetector
from piighost.linker.entity import ExactEntityLinker
from piighost.pipeline.thread import ThreadAnonymizationPipeline
from piighost.placeholder import CounterPlaceholderFactory
from piighost.resolver.entity import MergeEntityConflictResolver
from piighost.resolver.span import ConfidenceSpanConflictResolver

pytestmark = pytest.mark.asyncio


def _pipeline(words: list[tuple[str, str]]) -> ThreadAnonymizationPipeline:
    return ThreadAnonymizationPipeline(
        detector=ExactMatchDetector(words),
        span_resolver=ConfidenceSpanConflictResolver(),
        entity_linker=ExactEntityLinker(),
        entity_resolver=MergeEntityConflictResolver(),
        anonymizer=Anonymizer(CounterPlaceholderFactory()),
    )


async def test_batch_results_match_sequential():
    pipeline_seq = _pipeline([("Patrick", "PERSON"), ("Paris", "LOCATION")])
    pipeline_bat = _pipeline([("Patrick", "PERSON"), ("Paris", "LOCATION")])
    texts = [
        "Patrick habite à Paris.",
        "Paris est grande.",
        "Patrick revient demain.",
    ]
    sequential = [
        (await pipeline_seq.anonymize(t, thread_id="t1"))[0] for t in texts
    ]
    batch = [r for r, _ in await pipeline_bat.anonymize_batch(texts, thread_id="t1")]

    assert sequential == batch


async def test_batch_empty_returns_empty():
    pipeline = _pipeline([("Patrick", "PERSON")])
    result = await pipeline.anonymize_batch([], thread_id="t1")
    assert result == []


async def test_batch_preserves_entity_counters_across_messages():
    pipeline = _pipeline([("Patrick", "PERSON")])
    texts = ["Patrick arriva.", "Patrick repartit.", "Patrick téléphona."]
    results = await pipeline.anonymize_batch(texts, thread_id="t1")
    for anonymized, _ in results:
        assert "<<PERSON_1>>" in anonymized
        assert "Patrick" not in anonymized


async def test_batch_thread_isolation():
    pipeline = _pipeline([("Patrick", "PERSON")])
    texts = ["Patrick arriva.", "Patrick repartit."]
    r1 = await pipeline.anonymize_batch(texts, thread_id="thread_a")
    r2 = await pipeline.anonymize_batch(texts, thread_id="thread_b")
    assert r1[0][0] == r2[0][0]


async def test_max_threads_evicts_oldest_thread():
    pipeline2 = ThreadAnonymizationPipeline(
        detector=ExactMatchDetector([("Patrick", "PERSON")]),
        span_resolver=ConfidenceSpanConflictResolver(),
        entity_linker=ExactEntityLinker(),
        entity_resolver=MergeEntityConflictResolver(),
        anonymizer=Anonymizer(CounterPlaceholderFactory()),
        max_threads=2,
    )
    await pipeline2.anonymize("Patrick arriva.", thread_id="t1")
    await pipeline2.anonymize("Patrick repartit.", thread_id="t2")
    # Adding t3 should evict t1 (LRU)
    await pipeline2.anonymize("Patrick téléphona.", thread_id="t3")
    assert "t1" not in pipeline2._memories
    assert "t2" in pipeline2._memories
    assert "t3" in pipeline2._memories
