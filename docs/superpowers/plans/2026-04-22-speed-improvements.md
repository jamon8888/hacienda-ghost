# PIIGhost Speed Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PIIGhost's anonymization pipeline measurably faster across both real-time single-message and batch conversation-thread workloads, on CPU and GPU.

**Architecture:** Three independent phases — (1) benchmark harness to establish baselines, (2) algorithmic fixes to secondary bottlenecks (pure-Python stages), (3) inference acceleration targeting the 85% of latency in GLiNER2 model calls. Each phase ships as its own PR and is independently useful.

**Tech Stack:** Python 3.10+, uv, pytest, pytest-benchmark, aiocache, GLiNER2, asyncio

---

## File Map

**Phase 1 — Create:**
- `tests/benchmarks/__init__.py`
- `tests/benchmarks/bench_resolver.py`
- `tests/benchmarks/bench_linker.py`
- `tests/benchmarks/bench_pipeline.py`

**Phase 2 — Modify:**
- `src/piighost/resolver/entity.py` — replace O(n³) loop with Union-Find in `MergeEntityConflictResolver.resolve()`
- `src/piighost/linker/entity.py` — add `_pattern_cache` to `ExactEntityLinker`, override `_find_all()`
- `src/piighost/detector/base.py` — add `__post_init__` to `RegexDetector` to compile patterns once

**Phase 3 — Modify:**
- `src/piighost/detector/gliner2.py` — add `batch_size`, `quantize`, `compile_model` args; add `detect_batch()`
- `src/piighost/pipeline/thread.py` — add `anonymize_batch()` to `ThreadAnonymizationPipeline`; add LRU thread eviction via `OrderedDict` + `max_threads` arg

---

## Phase 1 — Benchmark Harness

### Task 1: Add pytest-benchmark dependency and benchmark directory

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/benchmarks/__init__.py`

- [ ] **Step 1: Add pytest-benchmark to dev dependency group in pyproject.toml**

In `pyproject.toml`, find the `[dependency-groups]` section and add `pytest-benchmark` to `dev`:

```toml
[dependency-groups]
dev = [
    "ruff>=0.15.5",
    "pytest>=9.0.2",
    "pytest-cov>=6.0",
    "pyrefly>=0.55.0",
    "zensical>=0.0.27",
    "commitizen>=4.13.9",
    "pytest-asyncio>=0.25",
    "pytest-benchmark>=5.1",
]
```

- [ ] **Step 2: Install the new dependency**

```bash
uv sync
```

Expected: resolves and installs `pytest-benchmark`.

- [ ] **Step 3: Create the benchmarks package**

Create `tests/benchmarks/__init__.py` as an empty file.

- [ ] **Step 4: Verify pytest-benchmark is available**

```bash
uv run pytest --co -q tests/benchmarks/ 2>&1 | head -5
```

Expected: `no tests ran` (no tests yet, but no import errors).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/benchmarks/__init__.py uv.lock
git commit -m "build: add pytest-benchmark dev dependency"
```

---

### Task 2: Resolver benchmark

**Files:**
- Create: `tests/benchmarks/bench_resolver.py`

- [ ] **Step 1: Create `tests/benchmarks/bench_resolver.py`**

```python
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
```

- [ ] **Step 2: Run and save baseline**

```bash
uv run pytest tests/benchmarks/bench_resolver.py -v --benchmark-autosave
```

Expected: 3 tests PASSED. Note the `mean` time for each in the output — these are your baseline numbers to beat in Phase 2.

- [ ] **Step 3: Commit**

```bash
git add tests/benchmarks/bench_resolver.py
git commit -m "bench: add resolver benchmark (5/20/50 conflicting entities)"
```

---

### Task 3: Linker benchmark

**Files:**
- Create: `tests/benchmarks/bench_linker.py`

- [ ] **Step 1: Create `tests/benchmarks/bench_linker.py`**

```python
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
    """n unique entity names, each appearing once in text, text repeats all 3 times."""
    names = [f"Person{i:03d}" for i in range(n)]
    # Each name appears once as seed detection; text repeats all names twice more
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
```

- [ ] **Step 2: Run and save baseline**

```bash
uv run pytest tests/benchmarks/bench_linker.py -v --benchmark-autosave
```

Expected: 3 tests PASSED. Note `mean` times.

- [ ] **Step 3: Commit**

```bash
git add tests/benchmarks/bench_linker.py
git commit -m "bench: add linker benchmark (5/15/30 detections)"
```

---

### Task 4: Pipeline end-to-end benchmark

**Files:**
- Create: `tests/benchmarks/bench_pipeline.py`

- [ ] **Step 1: Create `tests/benchmarks/bench_pipeline.py`**

```python
"""End-to-end pipeline benchmarks at short/medium/long text sizes.

Uses ExactMatchDetector (no model) to isolate pipeline overhead from
inference latency. Run bench_detector.py separately for model timings.
"""
import asyncio
import pytest

from piighost.anonymizer import Anonymizer
from piighost.detector import ExactMatchDetector
from piighost.linker.entity import ExactEntityLinker
from piighost.pipeline.base import AnonymizationPipeline
from piighost.placeholder import CounterPlaceholderFactory
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
        anonymizer=Anonymizer(CounterPlaceholderFactory()),
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
```

- [ ] **Step 2: Run and save baseline**

```bash
uv run pytest tests/benchmarks/bench_pipeline.py -v --benchmark-autosave
```

Expected: 3 tests PASSED. Note `mean` times — compare against Phase 2 results.

- [ ] **Step 3: Commit**

```bash
git add tests/benchmarks/bench_pipeline.py
git commit -m "bench: add pipeline end-to-end benchmark (short/medium/long)"
```

---

## Phase 2 — Algorithmic Fixes

### Task 5: Replace O(n³) loop with Union-Find in `MergeEntityConflictResolver`

**Files:**
- Modify: `src/piighost/resolver/entity.py:75-126`
- Test: `tests/resolver/test_entity_conflict_resolver.py` (existing, no new tests needed — correctness guaranteed by existing suite)

- [ ] **Step 1: Run existing resolver tests to confirm they pass before touching anything**

```bash
uv run pytest tests/resolver/test_entity_conflict_resolver.py -v
```

Expected: all tests PASS.

- [ ] **Step 2: Replace `resolve()` in `MergeEntityConflictResolver` (lines 75–126)**

Open `src/piighost/resolver/entity.py` and replace the `resolve` method of `MergeEntityConflictResolver` (lines 75–126) with:

```python
    def resolve(self, entities: list[Entity]) -> list[Entity]:
        """Merge all entities that share common detections transitively.

        Uses a Union-Find algorithm to efficiently group entities that
        are connected through shared detections.

        Args:
            entities: The full list of entities.

        Returns:
            A merged list of entities with no shared detections,
            sorted by earliest ``start_pos``.
        """
        if not entities:
            return []

        n = len(entities)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]  # path halving
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            root_x, root_y = find(x), find(y)
            if root_x != root_y:
                parent[root_x] = root_y

        for i in range(n):
            for j in range(i + 1, n):
                if self.have_conflict(entities[i], entities[j]):
                    union(i, j)

        groups: dict[int, list[int]] = {}
        for i in range(n):
            root = find(i)
            if root not in groups:
                groups[root] = []
            groups[root].append(i)

        result: list[Entity] = []
        for indices in groups.values():
            seen: set[Detection] = set()
            merged: list[Detection] = []
            for idx in indices:
                for d in entities[idx].detections:
                    if d not in seen:
                        seen.add(d)
                        merged.append(d)
            result.append(Entity(detections=tuple(merged)))

        result.sort(key=lambda e: min(d.position.start_pos for d in e.detections))
        return result
```

- [ ] **Step 3: Run existing resolver tests to confirm correctness**

```bash
uv run pytest tests/resolver/test_entity_conflict_resolver.py -v
```

Expected: all tests PASS. If any fail, the Union-Find implementation has a bug — check the `find()` and `union()` functions and the deduplication in the merge step.

- [ ] **Step 4: Run resolver benchmark to measure improvement**

```bash
uv run pytest tests/benchmarks/bench_resolver.py -v --benchmark-compare
```

Expected: `bench_resolver_50` should be significantly faster (target: 10x+ vs baseline for n=50).

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
uv run pytest tests/ -x -q --ignore=tests/benchmarks
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/resolver/entity.py
git commit -m "perf: replace O(n³) entity resolver loop with Union-Find"
```

---

### Task 6: Cache compiled regex patterns in `ExactEntityLinker`

**Files:**
- Modify: `src/piighost/linker/entity.py:105-113` (`__init__`), `src/piighost/linker/entity.py:240-250` (`_find_all`)
- Test: `tests/linker/test_exact_entity_linker.py` (existing)

- [ ] **Step 1: Run existing linker tests before touching anything**

```bash
uv run pytest tests/linker/test_exact_entity_linker.py -v
```

Expected: all tests PASS.

- [ ] **Step 2: Add `_pattern_cache` to `ExactEntityLinker.__init__()` (line 107)**

In `src/piighost/linker/entity.py`, find the `ExactEntityLinker` class. Add `_pattern_cache: dict[str, re.Pattern]` as a class-level annotation and initialize it in `__init__`:

```python
class ExactEntityLinker(BaseEntityLinker):
    _flags: re.RegexFlag
    _pattern_cache: dict[str, re.Pattern]

    def __init__(
        self,
        flags: re.RegexFlag = re.IGNORECASE,
        min_text_length: int = 1,
    ) -> None:
        super().__init__(min_text_length=min_text_length)
        self._flags = flags
        self._pattern_cache = {}
```

- [ ] **Step 3: Replace `_find_all()` (lines 240–250) to use the cache**

Replace the entire `_find_all` method with:

```python
    def _find_all(self, text: str, fragment: str) -> list[tuple[int, int]]:
        """Find all word-boundary occurrences of a fragment in the text.

        Compiled patterns are cached by fragment text so each unique
        entity string is only compiled once per linker instance.

        Args:
            text: The source text to search.
            fragment: The substring to look for.

        Returns:
            A list of ``(start, end)`` tuples for every match.
        """
        if fragment not in self._pattern_cache:
            escaped = re.escape(fragment)
            prefix = (
                r"\b"
                if fragment[0:1].isalnum() or fragment[0:1] == "_"
                else r"(?<!\w)"
            )
            suffix = (
                r"\b"
                if fragment[-1:].isalnum() or fragment[-1:] == "_"
                else r"(?!\w)"
            )
            self._pattern_cache[fragment] = re.compile(
                f"{prefix}{escaped}{suffix}", self._flags
            )
        return [
            (m.start(), m.end())
            for m in self._pattern_cache[fragment].finditer(text)
        ]
```

- [ ] **Step 4: Run linker tests to confirm correctness**

```bash
uv run pytest tests/linker/test_exact_entity_linker.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run linker benchmark to measure improvement**

```bash
uv run pytest tests/benchmarks/bench_linker.py -v --benchmark-compare
```

Expected: improvement on repeated entity names (target: 2x+ for n=15 and n=30).

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -x -q --ignore=tests/benchmarks
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/linker/entity.py
git commit -m "perf: cache compiled regex patterns in ExactEntityLinker"
```

---

### Task 7: Compile `RegexDetector` patterns at `__post_init__`

**Files:**
- Modify: `src/piighost/detector/base.py:197-241`
- Test: `tests/detector/test_regex_detector.py`, `tests/unit/detector/test_regex_detector.py`

- [ ] **Step 1: Run existing RegexDetector tests**

```bash
uv run pytest tests/detector/test_regex_detector.py tests/unit/detector/test_regex_detector.py -v
```

Expected: all tests PASS.

- [ ] **Step 2: Modify `RegexDetector` in `src/piighost/detector/base.py`**

Find the `RegexDetector` dataclass (line 197) and replace it entirely with:

```python
@dataclass
class RegexDetector:
    """Detect entities using regular expressions, one pattern per label.

    Useful for structured PII with a known format (phone numbers, IBANs,
    API keys, etc.) that a model-based detector may miss. Patterns are
    compiled once at construction time.

    Args:
        patterns: Mapping from entity label to a regex pattern string.

    Example:
        >>> detector = RegexDetector(patterns={"FR_PHONE": r"\\b(?:\\+33|0)[1-9](?:[\\s.\\-]?\\d{2}){4}\\b"})
        >>> detections = await detector.detect("Appelez le 06 12 34 56 78")
    """

    patterns: dict[str, str] = field(default_factory=dict)
    _compiled: dict[str, re.Pattern] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._compiled = {
            label: re.compile(pattern) for label, pattern in self.patterns.items()
        }

    async def detect(self, text: str) -> list[Detection]:
        """Find all regex matches for the configured patterns.

        Args:
            text: The input text to search for entities.

        Returns:
            One ``Detection`` per regex match, with ``confidence=1.0``.
        """
        detections: list[Detection] = []

        for label, compiled in self._compiled.items():
            for match in compiled.finditer(text):
                detections.append(
                    Detection(
                        text=match.group(),
                        label=label,
                        position=Span(
                            start_pos=match.start(),
                            end_pos=match.end(),
                        ),
                        confidence=1.0,
                    ),
                )

        return detections
```

- [ ] **Step 3: Run RegexDetector tests**

```bash
uv run pytest tests/detector/test_regex_detector.py tests/unit/detector/test_regex_detector.py -v
```

Expected: all tests PASS. If any test constructs a `RegexDetector` and then mutates `.patterns` after construction, it will fail — in that case check if the test should also be updated to not mutate after init (YAGNI: we don't support post-init pattern mutation).

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest tests/ -x -q --ignore=tests/benchmarks
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/detector/base.py
git commit -m "perf: compile RegexDetector patterns once at __post_init__"
```

---

### Task 8: Run Phase 2 benchmarks and compare against Phase 1 baseline

**Files:** none

- [ ] **Step 1: Compare all benchmarks against Phase 1 baseline**

```bash
uv run pytest tests/benchmarks/ -v --benchmark-compare --benchmark-compare-fail=mean:10%
```

Expected: resolver and linker benchmarks show improvement. Pipeline benchmark stays the same or improves slightly (it uses `ExactMatchDetector`, so linker improvement shows but resolver improvement shows only if many entities conflict).

- [ ] **Step 2: Commit comparison record**

```bash
git add .benchmarks/
git commit -m "bench: Phase 2 benchmark results vs Phase 1 baseline"
```

---

## Phase 3 — Inference Acceleration

### Task 9: Add hardware flags and `detect_batch()` to `Gliner2Detector`

**Files:**
- Modify: `src/piighost/detector/gliner2.py`
- Test: `tests/detector/` (add new test file)

- [ ] **Step 1: Write the failing test for hardware flags**

Create `tests/detector/test_gliner2_detector.py`:

```python
"""Tests for Gliner2Detector hardware flags and batch inference.

Skipped automatically if gliner2 is not installed.
Uses MagicMock as the model object — Python does not enforce type annotations
at runtime, so any object with the right methods works.
"""
import pytest
from unittest.mock import MagicMock

pytest.importorskip("gliner2", reason="gliner2 not installed")

from piighost.detector.gliner2 import Gliner2Detector  # noqa: E402


def _make_model() -> MagicMock:
    """Return a mock GLiNER2 model with canned responses."""
    model = MagicMock()
    model.extract_entities.return_value = {
        "entities": {
            "person": [{"text": "Patrick", "start": 0, "end": 7, "confidence": 0.95}]
        }
    }
    model.batch_extract_entities.return_value = [
        {
            "entities": {
                "person": [{"text": "Patrick", "start": 0, "end": 7, "confidence": 0.95}]
            }
        },
        {
            "entities": {
                "person": [{"text": "Jean", "start": 0, "end": 4, "confidence": 0.90}]
            }
        },
    ]
    return model


def test_quantize_flag_calls_model_quantize() -> None:
    model = _make_model()
    Gliner2Detector(model=model, labels=["PERSON"], quantize=True)
    model.quantize.assert_called_once()


def test_compile_model_flag_calls_model_compile() -> None:
    model = _make_model()
    Gliner2Detector(model=model, labels=["PERSON"], compile_model=True)
    model.compile.assert_called_once()


def test_no_flags_does_not_call_quantize_or_compile() -> None:
    model = _make_model()
    Gliner2Detector(model=model, labels=["PERSON"])
    model.quantize.assert_not_called()
    model.compile.assert_not_called()


@pytest.mark.asyncio
async def test_detect_batch_returns_list_matching_inputs() -> None:
    model = _make_model()
    detector = Gliner2Detector(model=model, labels={"PERSON": "person"}, batch_size=8)

    texts = ["Patrick arrived.", "Jean departed."]
    results = await detector.detect_batch(texts)

    assert len(results) == 2
    assert all(isinstance(r, list) for r in results)
    assert results[0][0].text == "Patrick"
    assert results[1][0].text == "Jean"
    model.batch_extract_entities.assert_called_once_with(
        texts,
        entity_types=["person"],
        threshold=0.5,
        include_spans=True,
        include_confidence=True,
        batch_size=8,
    )


@pytest.mark.asyncio
async def test_detect_batch_single_matches_detect() -> None:
    model = _make_model()
    model.batch_extract_entities.return_value = [
        {
            "entities": {
                "person": [{"text": "Patrick", "start": 0, "end": 7, "confidence": 0.95}]
            }
        }
    ]
    detector = Gliner2Detector(model=model, labels={"PERSON": "person"})

    single = await detector.detect("Patrick arrived.")
    batch = await detector.detect_batch(["Patrick arrived."])

    assert len(single) == len(batch[0])
    assert single[0].text == batch[0][0].text
    assert single[0].label == batch[0][0].label
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/detector/test_gliner2_detector.py -v
```

Expected: FAIL — `Gliner2Detector.__init__` does not accept `quantize`, `compile_model`, or `batch_size`; `detect_batch` does not exist.

- [ ] **Step 3: Implement hardware flags and `detect_batch()` in `src/piighost/detector/gliner2.py`**

Replace the entire file with:

```python
import importlib.util

from piighost.detector.base import BaseNERDetector
from piighost.models import Detection, Span

if importlib.util.find_spec("gliner2") is None:
    raise ImportError(
        "You must install gliner2 to use Gliner2Detector, please install piighost[gliner2] for use middleware"
    )

from gliner2 import GLiNER2


class Gliner2Detector(BaseNERDetector):
    """Detect entities using a GLiNER2 model.

    Wraps a ``GLiNER2`` model instance so that callers can inject a
    pre-loaded model (useful for tests and shared workers).

    Args:
        model: A loaded ``GLiNER2`` model instance.
        labels: Entity types this detector is configured to find.
        threshold: Minimum confidence score to keep a prediction.
        flat_ner: Whether to use flat NER mode (no nested entities).
        batch_size: Number of texts per batch for ``detect_batch()``.
            Defaults to ``1`` (sequential, backward-compatible).
        quantize: If ``True``, calls ``model.quantize()`` at init
            (fp16, GPU only).
        compile_model: If ``True``, calls ``model.compile()`` at init
            (torch.compile with fused kernels, GPU primary).

    Example:
        >>> from gliner2 import GLiNER2
        >>> model = GLiNER2.from_pretrained("fastino/gliner2-base-v1")
        >>> detector = Gliner2Detector(model=model, labels=["PERSON", "LOCATION"])
        >>> # GPU-optimised, batch of 8:
        >>> detector = Gliner2Detector(
        ...     model=model,
        ...     labels={"PERSON": "person"},
        ...     batch_size=8,
        ...     quantize=True,
        ...     compile_model=True,
        ... )
    """

    model: GLiNER2
    threshold: float
    flat_ner: bool
    batch_size: int

    def __init__(
        self,
        model: GLiNER2,
        labels: list[str] | dict[str, str],
        threshold: float = 0.5,
        flat_ner: bool = True,
        batch_size: int = 1,
        quantize: bool = False,
        compile_model: bool = False,
    ) -> None:
        super().__init__(labels)
        self.model = model
        self.threshold = threshold
        self.flat_ner = flat_ner
        self.batch_size = batch_size

        if quantize:
            self.model.quantize()
        if compile_model:
            self.model.compile()

    async def detect(self, text: str) -> list[Detection]:
        """Run GLiNER2 prediction and convert results to ``Detection`` objects.

        Args:
            text: The input text to search for entities.

        Returns:
            Detections whose score meets the configured threshold, with
            labels remapped to the external vocabulary.
        """
        raw_entities = self.model.extract_entities(
            text,
            entity_types=self.internal_labels,
            threshold=self.threshold,
            include_spans=True,
            include_confidence=True,
        )["entities"]

        detections: list[Detection] = []
        for entity_type, list_entity in raw_entities.items():
            external = self._map_label(entity_type)
            if external is None:
                continue
            for entity in list_entity:
                detections.append(
                    Detection(
                        text=entity["text"],
                        label=external,
                        position=Span(
                            start_pos=entity["start"],
                            end_pos=entity["end"],
                        ),
                        confidence=entity["confidence"],
                    )
                )

        return detections

    async def detect_batch(self, texts: list[str]) -> list[list[Detection]]:
        """Run batch GLiNER2 inference over multiple texts.

        Uses ``model.batch_extract_entities()`` to process all texts in
        a single model forward pass (GPU: significant throughput gain;
        CPU: reduced framework overhead). Falls back gracefully to
        sequential calls when ``texts`` is empty.

        Args:
            texts: List of input texts to process.

        Returns:
            One ``list[Detection]`` per input text, in the same order.
        """
        if not texts:
            return []

        raw_results = self.model.batch_extract_entities(
            texts,
            entity_types=self.internal_labels,
            threshold=self.threshold,
            include_spans=True,
            include_confidence=True,
            batch_size=self.batch_size,
        )

        all_detections: list[list[Detection]] = []
        for raw in raw_results:
            detections: list[Detection] = []
            for entity_type, list_entity in raw["entities"].items():
                external = self._map_label(entity_type)
                if external is None:
                    continue
                for entity in list_entity:
                    detections.append(
                        Detection(
                            text=entity["text"],
                            label=external,
                            position=Span(
                                start_pos=entity["start"],
                                end_pos=entity["end"],
                            ),
                            confidence=entity["confidence"],
                        )
                    )
            all_detections.append(detections)

        return all_detections
```

- [ ] **Step 4: Run the new tests**

```bash
uv run pytest tests/detector/test_gliner2_detector.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -x -q --ignore=tests/benchmarks
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/detector/gliner2.py tests/detector/test_gliner2_detector.py
git commit -m "feat(detector): add batch_size, quantize, compile_model flags and detect_batch() to Gliner2Detector"
```

---

### Task 10: Add `anonymize_batch()` to `ThreadAnonymizationPipeline`

**Files:**
- Modify: `src/piighost/pipeline/thread.py`
- Test: `tests/pipeline/` (add to existing file)

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_pipeline_batch.py`:

```python
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
    # All three should use the same token <<PERSON_1>> for Patrick
    for anonymized, _ in results:
        assert "<<PERSON_1>>" in anonymized
        assert "Patrick" not in anonymized


async def test_batch_thread_isolation():
    pipeline = _pipeline([("Patrick", "PERSON")])
    texts = ["Patrick arriva.", "Patrick repartit."]
    r1 = await pipeline.anonymize_batch(texts, thread_id="thread_a")
    r2 = await pipeline.anonymize_batch(texts, thread_id="thread_b")
    # Both threads should produce consistent output independently
    assert r1[0][0] == r2[0][0]
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/pipeline/test_pipeline_batch.py -v
```

Expected: FAIL — `ThreadAnonymizationPipeline` has no `anonymize_batch` method.

- [ ] **Step 3: Add `anonymize_batch()` to `ThreadAnonymizationPipeline` in `src/piighost/pipeline/thread.py`**

Add the following method to `ThreadAnonymizationPipeline`, after the existing `anonymize()` method (after line 335):

```python
    async def anonymize_batch(
        self,
        texts: list[str],
        thread_id: str = "default",
    ) -> list[tuple[str, list[Entity]]]:
        """Anonymize multiple texts for the same thread in one call.

        Uses ``detect_batch()`` if the detector exposes it (e.g.
        ``Gliner2Detector`` with ``batch_size > 1``), allowing a single
        model forward pass for all texts. Entity linking and memory
        recording are sequential to preserve placeholder counter order
        across messages.

        Args:
            texts: Ordered list of texts to anonymize.
            thread_id: Thread identifier for memory and cache isolation.

        Returns:
            One ``(anonymized_text, entities)`` tuple per input text,
            in the same order as ``texts``.
        """
        if not texts:
            return []

        self._thread_id = thread_id
        memory = self.get_memory(thread_id)

        # Detect all texts: use batch API if available, else sequential
        if hasattr(self._detector, "detect_batch"):
            raw_detections = await self._detector.detect_batch(texts)
        else:
            raw_detections = [await self._cached_detect(t) for t in texts]

        results: list[tuple[str, list[Entity]]] = []
        for text, detections in zip(texts, raw_detections):
            detections = self._span_resolver.resolve(detections)
            entities = self._entity_linker.link(text, detections)
            entities = self._entity_resolver.resolve(entities)
            entities = self._entity_linker.link_entities(
                entities, memory.all_entities
            )
            memory.record(hash_sha256(text), entities)
            anonymized = self.anonymize_with_ent(text, thread_id=thread_id)
            await self._store_mapping(text, anonymized, entities)
            results.append((anonymized, entities))

        return results
```

Make sure `hash_sha256` is already imported at the top of `thread.py` — it already is (`from piighost.utils import hash_sha256`).

Also make sure `Entity` is imported — it already is (`from piighost.models import Detection, Entity`).

- [ ] **Step 4: Run the new tests**

```bash
uv run pytest tests/pipeline/test_pipeline_batch.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run the full test suite**

```bash
uv run pytest tests/ -x -q --ignore=tests/benchmarks
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/pipeline/thread.py tests/pipeline/test_pipeline_batch.py
git commit -m "feat(pipeline): add anonymize_batch() to ThreadAnonymizationPipeline"
```

---

### Task 11: Add LRU thread eviction to `ThreadAnonymizationPipeline`

**Files:**
- Modify: `src/piighost/pipeline/thread.py`
- Test: `tests/pipeline/test_pipeline_memory.py` (existing + new cases)

- [ ] **Step 1: Write the failing test**

Add to `tests/pipeline/test_pipeline_batch.py` (append at the bottom):

```python
async def test_max_threads_evicts_oldest_thread():
    pipeline = _pipeline([("Patrick", "PERSON")])
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
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/pipeline/test_pipeline_batch.py::test_max_threads_evicts_oldest_thread -v
```

Expected: FAIL — `ThreadAnonymizationPipeline.__init__` does not accept `max_threads`; `_memories` is a plain dict.

- [ ] **Step 3: Add `OrderedDict` and `max_threads` to `ThreadAnonymizationPipeline`**

In `src/piighost/pipeline/thread.py`, add `from collections import OrderedDict` at the top (after existing imports).

Then update `ThreadAnonymizationPipeline.__init__()`:

```python
    def __init__(
        self,
        detector: AnyDetector,
        anonymizer: AnyAnonymizer,
        entity_linker: AnyEntityLinker | None = None,
        entity_resolver: AnyEntityConflictResolver | None = None,
        span_resolver: AnySpanConflictResolver | None = None,
        max_threads: int = 100,
    ) -> None:
        factory = anonymizer.ph_factory
        if isinstance(factory, (RedactPlaceholderFactory, MaskPlaceholderFactory)):
            raise ValueError(
                f"{type(factory).__name__} cannot be used with "
                f"ThreadAnonymizationPipeline because it produces "
                f"non-unique tokens that cannot be deanonymized. "
                f"Use CounterPlaceholderFactory or HashPlaceholderFactory instead."
            )

        super().__init__(
            detector,
            span_resolver=span_resolver,
            entity_linker=entity_linker,
            entity_resolver=entity_resolver,
            anonymizer=anonymizer,
        )

        self._memories: OrderedDict[str, ConversationMemory] = OrderedDict()
        self._max_threads = max_threads
        self._thread_id: str = "default"
```

Then update `get_memory()`:

```python
    def get_memory(self, thread_id: str = "default") -> ConversationMemory:
        """Return the memory for *thread_id*, evicting LRU if over limit."""
        if thread_id in self._memories:
            self._memories.move_to_end(thread_id)
            return self._memories[thread_id]

        if len(self._memories) >= self._max_threads:
            self._memories.popitem(last=False)  # evict least-recently-used

        self._memories[thread_id] = ConversationMemory()
        return self._memories[thread_id]
```

- [ ] **Step 4: Run the new test**

```bash
uv run pytest tests/pipeline/test_pipeline_batch.py::test_max_threads_evicts_oldest_thread -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test suite**

```bash
uv run pytest tests/ -x -q --ignore=tests/benchmarks
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/pipeline/thread.py tests/pipeline/test_pipeline_batch.py
git commit -m "feat(pipeline): add LRU thread eviction (max_threads) to ThreadAnonymizationPipeline"
```

---

### Task 12: Final benchmark comparison

**Files:** none

- [ ] **Step 1: Run all benchmarks and compare against Phase 1 baseline**

```bash
uv run pytest tests/benchmarks/ -v --benchmark-compare
```

Expected output includes: resolver 10x+ faster at n=50, linker 2x+ faster at n=15/30, pipeline unchanged (uses no-model detector).

- [ ] **Step 2: Run full test suite one last time**

```bash
uv run pytest tests/ -q --ignore=tests/benchmarks
```

Expected: all tests PASS.

- [ ] **Step 3: Commit benchmark results**

```bash
git add .benchmarks/
git commit -m "bench: Phase 3 final benchmark results"
```

---

## Out of Scope for This Plan

**OpenTelemetry spans** (from the design spec): Adding per-stage OTLP traces requires `opentelemetry-api` as a dependency and wrapping each pipeline stage. This is deferred — the benchmark suite in Phase 1 provides sufficient observability for development. Add OTel in a follow-on plan once Phase 3 ships and you have production traffic to trace.

---

## Flash Attention Note

To use FlashDeberta GPU acceleration with `Gliner2Detector`, set the environment variable **before** loading the model:

```python
import os
os.environ["USE_FLASHDEBERTA"] = "1"

from gliner2 import GLiNER2
from piighost.detector.gliner2 import Gliner2Detector

model = GLiNER2.from_pretrained("fastino/gliner2-base-v1", map_location="cuda")
detector = Gliner2Detector(model=model, labels=["PERSON"], batch_size=8, quantize=True)
```

Requires `pip install flashdeberta` separately. No code changes needed in PIIGhost.
