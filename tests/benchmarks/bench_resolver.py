"""Benchmarks for MergeEntityConflictResolver at 5, 20, and 50 conflicting entities."""
import pytest

from piighost.models import Detection, Entity, Span
from piighost.resolver.entity import MergeEntityConflictResolver


def _det(text: str, start: int) -> Detection:
    return Detection(
        text=text,
        label="PERSON",
        position=Span(start_pos=start, end_pos=start + len(text)),
        confidence=0.9,
    )


def _chain(n: int) -> list[Entity]:
    """n entities where entity[i] shares one detection with entity[i+1]."""
    shared = [_det(f"ent_{i}", i * 20) for i in range(n)]
    entities = []
    for i in range(n):
        dets = (shared[i], shared[i + 1]) if i < n - 1 else (shared[i],)
        entities.append(Entity(detections=dets))
    return entities


@pytest.mark.benchmark(group="resolver")
def test_bench_resolver_5(benchmark) -> None:
    entities = _chain(5)
    resolver = MergeEntityConflictResolver()
    result = benchmark(resolver.resolve, entities)
    assert len(result) == 1


@pytest.mark.benchmark(group="resolver")
def test_bench_resolver_20(benchmark) -> None:
    entities = _chain(20)
    resolver = MergeEntityConflictResolver()
    result = benchmark(resolver.resolve, entities)
    assert len(result) == 1


@pytest.mark.benchmark(group="resolver")
def test_bench_resolver_50(benchmark) -> None:
    entities = _chain(50)
    resolver = MergeEntityConflictResolver()
    result = benchmark(resolver.resolve, entities)
    assert len(result) == 1
