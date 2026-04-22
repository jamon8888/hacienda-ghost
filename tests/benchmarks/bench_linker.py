"""Benchmarks for ExactEntityLinker text expansion at 5, 15, and 30 detections."""
import pytest

from piighost.linker.entity import ExactEntityLinker
from piighost.models import Detection, Span


def _det(text: str, start: int) -> Detection:
    return Detection(
        text=text,
        label="PERSON",
        position=Span(start_pos=start, end_pos=start + len(text)),
        confidence=0.9,
    )


def _make_scenario(n: int) -> tuple[str, list[Detection]]:
    """n unique entity names, each appearing once as seed; text repeats all names 3 times."""
    names = [f"Person{i:03d}" for i in range(n)]
    text = " ".join(names) + ". " + " ".join(names) + ". " + " ".join(names)
    detections = []
    pos = 0
    for name in names:
        idx = text.find(name, pos)
        detections.append(_det(name, idx))
        pos = idx + len(name)
    return text, detections


@pytest.mark.benchmark(group="linker")
def test_bench_linker_5(benchmark) -> None:
    text, detections = _make_scenario(5)
    linker = ExactEntityLinker()
    result = benchmark(linker.link, text, detections)
    assert len(result) == 5


@pytest.mark.benchmark(group="linker")
def test_bench_linker_15(benchmark) -> None:
    text, detections = _make_scenario(15)
    linker = ExactEntityLinker()
    result = benchmark(linker.link, text, detections)
    assert len(result) == 15


@pytest.mark.benchmark(group="linker")
def test_bench_linker_30(benchmark) -> None:
    text, detections = _make_scenario(30)
    linker = ExactEntityLinker()
    result = benchmark(linker.link, text, detections)
    assert len(result) == 30
