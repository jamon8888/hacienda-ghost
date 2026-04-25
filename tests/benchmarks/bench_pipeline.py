"""End-to-end pipeline benchmarks at short/medium/long text sizes.

Uses ExactMatchDetector (no model) to isolate pipeline overhead from
inference latency.
"""
import asyncio
import pytest

from piighost.anonymizer import Anonymizer
from piighost.detector import ExactMatchDetector
from piighost.linker.entity import ExactEntityLinker
from piighost.pipeline.base import AnonymizationPipeline
from piighost.placeholder import LabelCounterPlaceholderFactory
from piighost.resolver.entity import MergeEntityConflictResolver
from piighost.resolver.span import ConfidenceSpanConflictResolver

_WORDS = [
    ("Patrick", "PERSON"),
    ("Google", "ORG"),
    ("Paris", "LOCATION"),
    ("Jean", "PERSON"),
    ("Lyon", "LOCATION"),
]

SHORT = "Patrick travaille chez Google à Paris."
MEDIUM = ("Patrick est ingénieur chez Google. " * 15) + "Jean est à Lyon."
LONG = ("Patrick travaille chez Google depuis 2020. " * 60) + "Jean et Paris aussi."


def _pipeline() -> AnonymizationPipeline:
    return AnonymizationPipeline(
        detector=ExactMatchDetector(_WORDS),
        span_resolver=ConfidenceSpanConflictResolver(),
        entity_linker=ExactEntityLinker(),
        entity_resolver=MergeEntityConflictResolver(),
        anonymizer=Anonymizer(LabelCounterPlaceholderFactory()),
    )


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.benchmark(group="pipeline")
def test_bench_pipeline_short(benchmark, event_loop) -> None:
    pipeline = _pipeline()
    result, _ = benchmark(lambda: event_loop.run_until_complete(pipeline.anonymize(SHORT)))
    assert "<<PERSON_1>>" in result


@pytest.mark.benchmark(group="pipeline")
def test_bench_pipeline_medium(benchmark, event_loop) -> None:
    pipeline = _pipeline()
    result, _ = benchmark(lambda: event_loop.run_until_complete(pipeline.anonymize(MEDIUM)))
    assert "<<PERSON_1>>" in result


@pytest.mark.benchmark(group="pipeline")
def test_bench_pipeline_long(benchmark, event_loop) -> None:
    pipeline = _pipeline()
    result, _ = benchmark(lambda: event_loop.run_until_complete(pipeline.anonymize(LONG)))
    assert "<<PERSON_1>>" in result
