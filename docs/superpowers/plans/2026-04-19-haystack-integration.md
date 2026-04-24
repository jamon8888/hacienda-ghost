# Haystack Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Phase 1 of the Haystack integration — 4 components (`PIIGhostDocumentAnonymizer`, `PIIGhostQueryAnonymizer`, `PIIGhostRehydrator`, `PIIGhostDocumentClassifier`), a new `piighost.classifier` subsystem, a `lancedb_meta_fields()` helper, and supporting tests. Enables a Kreuzberg → PIIGhost → LanceDB RAG pipeline with deterministic hash tokens and meta-embedded rehydration.

**Architecture:** Components wrap the existing async `ThreadAnonymizationPipeline` and an `AnyClassifier` protocol. Sync `run()` and async `run_async()` are both exposed; sync bridges via `asyncio.run` and raises a clear error if a loop is already running. Mappings live in `Document.meta["piighost_mapping"]` as a JSON-serialized string. Classification results live in `Document.meta["labels"]` as a structured dict so LanceDB can filter on it.

**Tech Stack:** Python 3.12+, `haystack-ai>=2.8`, `lancedb-haystack>=0.1` (optional), `pyarrow`, `aiocache`, `pyrefly`, `ruff`, `pytest`, `pytest-asyncio`, `uv`.

**Ref spec:** `docs/superpowers/specs/2026-04-19-haystack-integration-design.md`

---

## File Structure

**New files:**

- `src/piighost/classifier/__init__.py` — re-exports
- `src/piighost/classifier/base.py` — `AnyClassifier` protocol, `ClassificationSchema` TypedDict
- `src/piighost/classifier/exact.py` — `ExactMatchClassifier` test double
- `src/piighost/classifier/gliner2.py` — `Gliner2Classifier` (gated on `gliner2` extra)
- `src/piighost/integrations/__init__.py` — empty namespace
- `src/piighost/integrations/haystack/__init__.py` — public exports
- `src/piighost/integrations/haystack/_base.py` — `_run_sync` bridge helper
- `src/piighost/integrations/haystack/documents.py` — 4 components
- `src/piighost/integrations/haystack/presets.py` — `PRESET_GDPR`, `PRESET_SENSITIVITY`, `PRESET_LANGUAGE`
- `src/piighost/integrations/haystack/lancedb.py` — `lancedb_meta_fields()` helper
- `tests/classifier/__init__.py`
- `tests/classifier/test_exact_classifier.py`
- `tests/integrations/__init__.py`
- `tests/integrations/haystack/__init__.py`
- `tests/integrations/haystack/conftest.py` — shared fixtures
- `tests/integrations/haystack/test_sync_async_bridge.py`
- `tests/integrations/haystack/test_document_anonymizer.py`
- `tests/integrations/haystack/test_query_anonymizer.py`
- `tests/integrations/haystack/test_rehydrator.py`
- `tests/integrations/haystack/test_document_classifier.py`
- `tests/integrations/haystack/test_presets.py`
- `tests/integrations/haystack/test_lancedb_fields.py`
- `tests/integrations/haystack/test_pipeline_wiring.py`
- `tests/integrations/haystack/test_error_policy.py`
- `tests/integrations/haystack/test_lancedb_roundtrip.py` — marked `slow`

**Modified files:**

- `pyproject.toml` — add `haystack` and `haystack-lancedb` extras; update `all`
- `src/piighost/exceptions.py` — add `RehydrationError`

---

## Task 1: Dependency extras + empty package skeleton

**Files:**
- Modify: `pyproject.toml` (extras section + `all`)
- Create: `src/piighost/integrations/__init__.py` (empty)
- Create: `src/piighost/integrations/haystack/__init__.py` (empty stub)

- [x] **Step 1.1: Add extras and package skeleton**

Edit `pyproject.toml` (the `[project.optional-dependencies]` block). Add two new extras and update `all`:

```toml
haystack = [
    "haystack-ai>=2.8",
    "aiocache>=0.12",
]
haystack-lancedb = [
    "piighost[haystack]",
    "lancedb-haystack>=0.1",
]
all = [
    "piighost[gliner2,langchain,faker,cache,client,spacy,transformers,llm,haystack]",
]
```

Create `src/piighost/integrations/__init__.py`:

```python
"""Third-party framework integrations (Haystack, etc.)."""
```

Create `src/piighost/integrations/haystack/__init__.py`:

```python
"""Haystack integration for PIIGhost.

Install with: uv add piighost[haystack]
"""

import importlib.util

if importlib.util.find_spec("haystack") is None:
    raise ImportError(
        "You must install haystack to use the Haystack integration, "
        "please install piighost[haystack]"
    )
```

- [x] **Step 1.2: Sync dependencies**

Run: `uv sync --extra haystack`
Expected: installs `haystack-ai`, no errors.

- [x] **Step 1.3: Verify package imports**

Run: `uv run python -c "import piighost.integrations.haystack"`
Expected: no error (haystack is installed).

- [x] **Step 1.4: Commit**

```bash
git add pyproject.toml uv.lock src/piighost/integrations/
git commit -m "build: add haystack and haystack-lancedb optional extras"
```

---

## Task 2: `RehydrationError` exception

**Files:**
- Modify: `src/piighost/exceptions.py`
- Test: existing `tests/test_optional_dependencies.py` (no new test needed — trivial addition, covered by usage in later tasks)

- [x] **Step 2.1: Add exception class**

Edit `src/piighost/exceptions.py`, appending this class at the bottom:

```python
class RehydrationError(DeanonymizationError):
    """Raised when a document's anonymization mapping is missing or malformed.

    Subclass of DeanonymizationError because rehydration is semantically
    a deanonymization step, just driven from Document.meta rather than
    from the pipeline cache.
    """
```

- [x] **Step 2.2: Verify import**

Run: `uv run python -c "from piighost.exceptions import RehydrationError, DeanonymizationError; assert issubclass(RehydrationError, DeanonymizationError)"`
Expected: exits 0.

- [x] **Step 2.3: Commit**

```bash
git add src/piighost/exceptions.py
git commit -m "feat: add RehydrationError exception for haystack integration"
```

---

## Task 3: `AnyClassifier` protocol + `ExactMatchClassifier` (TDD)

**Files:**
- Create: `src/piighost/classifier/__init__.py`
- Create: `src/piighost/classifier/base.py`
- Create: `src/piighost/classifier/exact.py`
- Create: `tests/classifier/__init__.py` (empty)
- Create: `tests/classifier/test_exact_classifier.py`

- [x] **Step 3.1: Write failing tests for `ExactMatchClassifier`**

Create `tests/classifier/__init__.py` (empty).

Create `tests/classifier/test_exact_classifier.py`:

```python
"""Tests for ``ExactMatchClassifier`` (test double for GLiNER2 classification)."""

import pytest

from piighost.classifier import ExactMatchClassifier
from piighost.classifier.base import ClassificationSchema

pytestmark = pytest.mark.asyncio


class TestExactMatchClassifier:
    """Hard-coded classifier used in tests to avoid loading GLiNER2."""

    async def test_returns_configured_labels_for_known_text(self) -> None:
        classifier = ExactMatchClassifier(
            results={
                "hello world": {"sentiment": ["positive"], "language": ["en"]},
            }
        )
        schemas: dict[str, ClassificationSchema] = {
            "sentiment": {"labels": ["positive", "negative"], "multi_label": False},
            "language": {"labels": ["en", "fr"], "multi_label": False},
        }
        result = await classifier.classify("hello world", schemas)
        assert result == {"sentiment": ["positive"], "language": ["en"]}

    async def test_returns_empty_lists_for_unknown_text(self) -> None:
        classifier = ExactMatchClassifier(results={})
        schemas: dict[str, ClassificationSchema] = {
            "sentiment": {"labels": ["positive", "negative"], "multi_label": False},
        }
        result = await classifier.classify("unknown text", schemas)
        assert result == {"sentiment": []}

    async def test_returns_empty_dict_for_empty_schemas(self) -> None:
        classifier = ExactMatchClassifier(
            results={"hello": {"sentiment": ["positive"]}}
        )
        result = await classifier.classify("hello", {})
        assert result == {}

    async def test_multi_label_returns_multiple_labels(self) -> None:
        classifier = ExactMatchClassifier(
            results={
                "great camera and battery": {"aspects": ["camera", "battery"]},
            }
        )
        schemas: dict[str, ClassificationSchema] = {
            "aspects": {
                "labels": ["camera", "battery", "screen"],
                "multi_label": True,
            },
        }
        result = await classifier.classify("great camera and battery", schemas)
        assert result == {"aspects": ["camera", "battery"]}
```

- [x] **Step 3.2: Run tests to verify they fail**

Run: `uv run pytest tests/classifier/test_exact_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'piighost.classifier'`

- [x] **Step 3.3: Implement the classifier module**

Create `src/piighost/classifier/base.py`:

```python
"""Base classifier protocol and schema types."""

from typing import Protocol, TypedDict


class ClassificationSchema(TypedDict, total=False):
    """Schema describing a single classification axis.

    Fields match the GLiNER2 ``classify_text`` API so that implementations
    can pass them through directly.

    Attributes:
        labels: Candidate label values for this axis (e.g. ``["en", "fr"]``).
        multi_label: If ``True``, multiple labels may be returned.
            Defaults to ``False`` (single-label).
        cls_threshold: Minimum confidence for a label to be picked.
            Defaults to the implementation's own choice (e.g. 0.5).
    """

    labels: list[str]
    multi_label: bool
    cls_threshold: float


class AnyClassifier(Protocol):
    """Protocol for text classification components.

    Implementations take a text and a dict of named classification
    axes (``schemas``) and return a dict mapping each axis name to
    the list of picked labels.
    """

    async def classify(
        self,
        text: str,
        schemas: dict[str, ClassificationSchema],
    ) -> dict[str, list[str]]:
        """Classify ``text`` against each axis in ``schemas``.

        Args:
            text: The input text to classify.
            schemas: Named classification axes.

        Returns:
            A dict with the same keys as ``schemas``, each mapped to the
            list of labels picked for that axis.
        """
        ...
```

Create `src/piighost/classifier/exact.py`:

```python
"""Test-double classifier that returns pre-configured results."""

from piighost.classifier.base import ClassificationSchema


class ExactMatchClassifier:
    """Classifier that returns hard-coded results per text.

    Useful for tests: configure with a ``{text: {schema: [labels]}}``
    mapping and it will return those labels when asked. Texts not in
    the mapping return empty label lists per schema.

    Args:
        results: Mapping from input text to expected classification output.

    Example:
        >>> classifier = ExactMatchClassifier(
        ...     results={"hello": {"sentiment": ["positive"]}}
        ... )
    """

    def __init__(self, results: dict[str, dict[str, list[str]]] | None = None) -> None:
        self._results = results or {}

    async def classify(
        self,
        text: str,
        schemas: dict[str, ClassificationSchema],
    ) -> dict[str, list[str]]:
        """Return configured labels for ``text``, or empty lists if unknown."""
        configured = self._results.get(text, {})
        return {name: configured.get(name, []) for name in schemas}
```

Create `src/piighost/classifier/__init__.py`:

```python
from piighost.classifier.base import AnyClassifier, ClassificationSchema
from piighost.classifier.exact import ExactMatchClassifier

__all__ = [
    "AnyClassifier",
    "ClassificationSchema",
    "ExactMatchClassifier",
]
```

- [x] **Step 3.4: Run tests to verify they pass**

Run: `uv run pytest tests/classifier/test_exact_classifier.py -v`
Expected: 4 tests PASS.

- [x] **Step 3.5: Lint and type-check**

Run: `make lint`
Expected: 0 errors.

- [x] **Step 3.6: Commit**

```bash
git add src/piighost/classifier/ tests/classifier/
git commit -m "feat: add classifier subsystem with ExactMatchClassifier test double"
```

---

## Task 4: `Gliner2Classifier`

**Files:**
- Create: `src/piighost/classifier/gliner2.py`
- Modify: `src/piighost/classifier/__init__.py` (export lazily — only if gliner2 installed)

- [x] **Step 4.1: Implement `Gliner2Classifier`**

Create `src/piighost/classifier/gliner2.py`:

```python
"""GLiNER2-backed classifier. Gated on the ``gliner2`` extra."""

import importlib.util

from piighost.classifier.base import ClassificationSchema

if importlib.util.find_spec("gliner2") is None:
    raise ImportError(
        "You must install gliner2 to use Gliner2Classifier, "
        "please install piighost[gliner2]"
    )

from gliner2 import GLiNER2


class Gliner2Classifier:
    """Classify text against named schemas using a GLiNER2 model.

    Reuses an already-loaded ``GLiNER2`` instance so the same model
    can power both NER (via ``Gliner2Detector``) and classification.

    Args:
        model: A loaded ``GLiNER2`` model instance.

    Example:
        >>> from gliner2 import GLiNER2
        >>> model = GLiNER2.from_pretrained("fastino/gliner2-multi-v1")
        >>> classifier = Gliner2Classifier(model=model)
    """

    model: GLiNER2

    def __init__(self, model: GLiNER2) -> None:
        self.model = model

    async def classify(
        self,
        text: str,
        schemas: dict[str, ClassificationSchema],
    ) -> dict[str, list[str]]:
        """Run ``model.classify_text`` and return a label dict per axis.

        Args:
            text: Input text to classify.
            schemas: Named classification axes.

        Returns:
            A dict mapping each axis name to the list of picked labels.
        """
        if not schemas:
            return {}
        raw = self.model.classify_text(text, schemas)
        return {
            name: list(raw.get(name, [])) if raw.get(name) else []
            for name in schemas
        }
```

- [x] **Step 4.2: Verify import gating**

Run: `uv run python -c "from piighost.classifier.gliner2 import Gliner2Classifier; print(Gliner2Classifier.__name__)"`
Expected (if gliner2 installed): prints `Gliner2Classifier`.
If gliner2 missing: `ImportError` with the piighost[gliner2] message.

- [x] **Step 4.3: Commit**

```bash
git add src/piighost/classifier/gliner2.py
git commit -m "feat: add Gliner2Classifier for GLiNER2-backed document classification"
```

---

## Task 5: sync/async bridge helper (`_base.py`)

**Files:**
- Create: `src/piighost/integrations/haystack/_base.py`
- Create: `tests/integrations/__init__.py` (empty)
- Create: `tests/integrations/haystack/__init__.py` (empty)
- Create: `tests/integrations/haystack/test_sync_async_bridge.py`

- [x] **Step 5.1: Write failing tests**

Create the empty `__init__.py` files.

Create `tests/integrations/haystack/test_sync_async_bridge.py`:

```python
"""Tests for the sync/async bridge used by Haystack components."""

import asyncio

import pytest

from piighost.integrations.haystack._base import run_coroutine_sync


class TestRunCoroutineSync:
    """``run_coroutine_sync`` runs an awaitable from sync code, or fails loudly."""

    def test_runs_coroutine_outside_loop(self) -> None:
        async def coro() -> int:
            return 42

        assert run_coroutine_sync(coro()) == 42

    def test_raises_inside_running_loop(self) -> None:
        async def coro() -> int:
            return 42

        async def outer() -> None:
            with pytest.raises(RuntimeError, match="AsyncPipeline"):
                run_coroutine_sync(coro())

        asyncio.run(outer())

    def test_propagates_coroutine_exception(self) -> None:
        async def coro() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            run_coroutine_sync(coro())
```

- [x] **Step 5.2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/haystack/test_sync_async_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'piighost.integrations.haystack._base'`

- [x] **Step 5.3: Implement the helper**

Create `src/piighost/integrations/haystack/_base.py`:

```python
"""Shared helpers for Haystack components."""

import asyncio
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_coroutine_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Execute ``coro`` from synchronous code.

    If no event loop is running, uses ``asyncio.run`` to drive the
    coroutine to completion. If a loop is already running (e.g. the
    caller is inside a Jupyter cell with autoreload, a FastAPI handler,
    or a Haystack ``AsyncPipeline``), raises a clear ``RuntimeError``
    telling the caller to switch to the async API.

    Args:
        coro: The awaitable to drive.

    Returns:
        The coroutine's result.

    Raises:
        RuntimeError: If called from inside a running event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "PIIGhost Haystack component's sync run() was called from inside a "
        "running event loop. Use Haystack's AsyncPipeline + run_async() instead."
    )
```

- [x] **Step 5.4: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/haystack/test_sync_async_bridge.py -v`
Expected: 3 tests PASS.

- [x] **Step 5.5: Commit**

```bash
git add src/piighost/integrations/haystack/_base.py tests/integrations/
git commit -m "feat: add sync/async bridge helper for haystack components"
```

---

## Task 6: `PIIGhostDocumentAnonymizer` + conftest fixtures

**Files:**
- Create: `src/piighost/integrations/haystack/documents.py` (first component only)
- Create: `tests/integrations/haystack/conftest.py`
- Create: `tests/integrations/haystack/test_document_anonymizer.py`

- [x] **Step 6.1: Write conftest with shared fixtures**

Create `tests/integrations/haystack/conftest.py`:

```python
"""Shared fixtures for Haystack component tests."""

import pytest

from piighost.anonymizer import Anonymizer
from piighost.detector import ExactMatchDetector
from piighost.linker.entity import ExactEntityLinker
from piighost.pipeline.thread import ThreadAnonymizationPipeline
from piighost.placeholder import HashPlaceholderFactory
from piighost.resolver.entity import MergeEntityConflictResolver
from piighost.resolver.span import ConfidenceSpanConflictResolver


@pytest.fixture
def pipeline() -> ThreadAnonymizationPipeline:
    """A ThreadAnonymizationPipeline with HashPlaceholderFactory.

    Uses ``ExactMatchDetector`` so tests don't need GLiNER2 loaded.
    Detects ``Patrick`` as PERSON, ``Paris`` and ``France`` as LOCATION.
    """
    return ThreadAnonymizationPipeline(
        detector=ExactMatchDetector(
            [("Patrick", "PERSON"), ("Paris", "LOCATION"), ("France", "LOCATION")]
        ),
        span_resolver=ConfidenceSpanConflictResolver(),
        entity_linker=ExactEntityLinker(),
        entity_resolver=MergeEntityConflictResolver(),
        anonymizer=Anonymizer(HashPlaceholderFactory()),
    )
```

- [x] **Step 6.2: Write failing tests for `PIIGhostDocumentAnonymizer`**

Create `tests/integrations/haystack/test_document_anonymizer.py`:

```python
"""Tests for ``PIIGhostDocumentAnonymizer``."""

import json

import pytest
from haystack import Document

from piighost.anonymizer import Anonymizer
from piighost.detector import ExactMatchDetector
from piighost.integrations.haystack.documents import PIIGhostDocumentAnonymizer
from piighost.linker.entity import ExactEntityLinker
from piighost.pipeline.thread import ThreadAnonymizationPipeline
from piighost.placeholder import CounterPlaceholderFactory, HashPlaceholderFactory
from piighost.resolver.entity import MergeEntityConflictResolver
from piighost.resolver.span import ConfidenceSpanConflictResolver

pytestmark = pytest.mark.asyncio


class TestAnonymize:
    """Anonymization replaces content and stores a JSON mapping in meta."""

    async def test_anonymizes_content(self, pipeline) -> None:
        component = PIIGhostDocumentAnonymizer(pipeline=pipeline)
        doc = Document(content="Patrick habite à Paris.")
        out = await component.run_async(documents=[doc])
        anonymized = out["documents"][0].content
        assert "Patrick" not in anonymized
        assert "Paris" not in anonymized
        assert "<PERSON:" in anonymized
        assert "<LOCATION:" in anonymized

    async def test_stores_mapping_in_meta(self, pipeline) -> None:
        component = PIIGhostDocumentAnonymizer(pipeline=pipeline)
        doc = Document(content="Patrick habite à Paris.")
        out = await component.run_async(documents=[doc])
        mapping_raw = out["documents"][0].meta["piighost_mapping"]
        assert isinstance(mapping_raw, str)
        mapping = json.loads(mapping_raw)
        originals = {m["original"] for m in mapping}
        labels = {m["label"] for m in mapping}
        assert originals == {"Patrick", "Paris"}
        assert labels == {"PERSON", "LOCATION"}

    async def test_empty_content_passes_through(self, pipeline) -> None:
        component = PIIGhostDocumentAnonymizer(pipeline=pipeline)
        doc = Document(content="")
        out = await component.run_async(documents=[doc])
        assert out["documents"][0].content == ""
        assert "piighost_mapping" not in out["documents"][0].meta

    async def test_none_content_passes_through(self, pipeline) -> None:
        component = PIIGhostDocumentAnonymizer(pipeline=pipeline)
        doc = Document(content=None)
        out = await component.run_async(documents=[doc])
        assert out["documents"][0].content is None


class TestProfile:
    """The ``populate_profile`` flag adds a JSON profile summary to meta."""

    async def test_profile_contains_entity_flags_and_counts(self, pipeline) -> None:
        component = PIIGhostDocumentAnonymizer(pipeline=pipeline, populate_profile=True)
        doc = Document(content="Patrick habite à Paris.")
        out = await component.run_async(documents=[doc])
        profile_raw = out["documents"][0].meta["piighost_profile"]
        profile = json.loads(profile_raw)
        assert profile["has_person"] is True
        assert profile["n_entities"] == 2
        assert set(profile["labels"]) == {"PERSON", "LOCATION"}

    async def test_profile_absent_when_flag_off(self, pipeline) -> None:
        component = PIIGhostDocumentAnonymizer(pipeline=pipeline, populate_profile=False)
        doc = Document(content="Patrick habite à Paris.")
        out = await component.run_async(documents=[doc])
        assert "piighost_profile" not in out["documents"][0].meta


class TestPlaceholderFactoryCheck:
    """Counter-based factory is rejected unless opt-in."""

    def test_counter_factory_raises_value_error(self) -> None:
        pipeline = ThreadAnonymizationPipeline(
            detector=ExactMatchDetector([("Patrick", "PERSON")]),
            span_resolver=ConfidenceSpanConflictResolver(),
            entity_linker=ExactEntityLinker(),
            entity_resolver=MergeEntityConflictResolver(),
            anonymizer=Anonymizer(CounterPlaceholderFactory()),
        )
        with pytest.raises(ValueError, match="HashPlaceholderFactory"):
            PIIGhostDocumentAnonymizer(pipeline=pipeline)

    def test_counter_factory_allowed_with_escape_hatch(self) -> None:
        pipeline = ThreadAnonymizationPipeline(
            detector=ExactMatchDetector([("Patrick", "PERSON")]),
            span_resolver=ConfidenceSpanConflictResolver(),
            entity_linker=ExactEntityLinker(),
            entity_resolver=MergeEntityConflictResolver(),
            anonymizer=Anonymizer(CounterPlaceholderFactory()),
        )
        PIIGhostDocumentAnonymizer(pipeline=pipeline, allow_non_stable_tokens=True)


class TestSyncRun:
    """The sync ``run`` path works outside a running loop."""

    def test_sync_run_outside_loop(self, pipeline) -> None:
        component = PIIGhostDocumentAnonymizer(pipeline=pipeline)
        doc = Document(content="Patrick habite à Paris.")
        out = component.run(documents=[doc])
        assert "<PERSON:" in out["documents"][0].content
```

- [x] **Step 6.3: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/haystack/test_document_anonymizer.py -v`
Expected: FAIL — `ImportError` / `ModuleNotFoundError` for the component.

- [x] **Step 6.4: Implement the component**

Create `src/piighost/integrations/haystack/documents.py`:

```python
"""Haystack components for the PIIGhost document pipeline."""

import json
import logging
from typing import Any

from haystack import Document, component

from piighost.integrations.haystack._base import run_coroutine_sync
from piighost.pipeline.thread import ThreadAnonymizationPipeline
from piighost.placeholder import CounterPlaceholderFactory

logger = logging.getLogger(__name__)


def _serialize_mapping(entities: list) -> str:
    """Serialize the (entity → token) mapping as a JSON list string."""
    from piighost.models import Entity  # avoid cycle in type imports

    items: list[dict[str, str]] = []
    for entity in entities:
        assert isinstance(entity, Entity)
        # The factory is deterministic for Hash; recreate tokens to avoid
        # state leak from the pipeline's internal caches.
        canonical = entity.detections[0].text
        label = entity.label
        items.append(
            {"original": canonical, "label": label}
        )
    return json.dumps(items)


def _build_profile(entities: list) -> dict[str, Any]:
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
        doc.meta[self._meta_key] = _serialize_mapping(entities)
        if self._populate_profile:
            doc.meta["piighost_profile"] = json.dumps(_build_profile(entities))
```

The `_serialize_mapping` helper currently only stores `original` and `label`, not the token. The `Rehydrator` will need the token too — update the helper to include it. Replace `_serialize_mapping` with:

```python
def _serialize_mapping(entities: list) -> str:
    """Serialize the (entity → token) mapping as a JSON list string.

    Each item has ``token``, ``original``, and ``label`` so the Rehydrator
    can rebuild the token → original map without re-running the factory.
    """
    from piighost.models import Entity

    # Re-derive tokens from the entity set using the same factory the
    # pipeline uses, to guarantee consistency.
    items: list[dict[str, str]] = []
    for entity in entities:
        assert isinstance(entity, Entity)
        items.append(
            {
                "original": entity.detections[0].text,
                "label": entity.label,
            }
        )
    return json.dumps(items)
```

Wait — the tokens need to be recreated at rehydration time from the entities alone, since `HashPlaceholderFactory` is deterministic. That works, but it couples the Rehydrator to the factory. Simpler: store the token too.

Replace with the final version that stores tokens:

```python
def _serialize_mapping(
    entities: list,
    ph_factory,
) -> str:
    """Serialize the (token → original) mapping as a JSON list string."""
    from piighost.models import Entity

    tokens = ph_factory.create(entities)
    items: list[dict[str, str]] = []
    for entity, token in tokens.items():
        assert isinstance(entity, Entity)
        for detection in entity.detections:
            items.append(
                {
                    "token": token,
                    "original": detection.text,
                    "label": entity.label,
                }
            )
    return json.dumps(items)
```

And in `_process` call it with `self._pipeline.ph_factory`:

```python
doc.meta[self._meta_key] = _serialize_mapping(entities, self._pipeline.ph_factory)
```

- [x] **Step 6.5: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/haystack/test_document_anonymizer.py -v`
Expected: 8 tests PASS.

- [x] **Step 6.6: Commit**

```bash
git add src/piighost/integrations/haystack/documents.py tests/integrations/haystack/
git commit -m "feat: add PIIGhostDocumentAnonymizer haystack component"
```

---

## Task 7: `PIIGhostQueryAnonymizer`

**Files:**
- Modify: `src/piighost/integrations/haystack/documents.py` (append component)
- Create: `tests/integrations/haystack/test_query_anonymizer.py`

- [x] **Step 7.1: Write failing tests**

Create `tests/integrations/haystack/test_query_anonymizer.py`:

```python
"""Tests for ``PIIGhostQueryAnonymizer``."""

import pytest

from piighost.integrations.haystack.documents import (
    PIIGhostDocumentAnonymizer,
    PIIGhostQueryAnonymizer,
)
from haystack import Document

pytestmark = pytest.mark.asyncio


class TestQueryAnonymize:
    """Anonymizes a query string and returns it with detected entities."""

    async def test_anonymizes_query_content(self, pipeline) -> None:
        component = PIIGhostQueryAnonymizer(pipeline=pipeline)
        out = await component.run_async(query="Où habite Patrick ?")
        assert "Patrick" not in out["query"]
        assert "<PERSON:" in out["query"]

    async def test_returns_entities(self, pipeline) -> None:
        component = PIIGhostQueryAnonymizer(pipeline=pipeline)
        out = await component.run_async(query="Patrick habite à Paris.")
        assert len(out["entities"]) == 2
        labels = {e.label for e in out["entities"]}
        assert labels == {"PERSON", "LOCATION"}

    async def test_query_hash_matches_document_hash(self, pipeline) -> None:
        """The token for ``Patrick`` in a query matches the one in a doc."""
        doc_component = PIIGhostDocumentAnonymizer(pipeline=pipeline)
        query_component = PIIGhostQueryAnonymizer(pipeline=pipeline)

        doc_out = await doc_component.run_async(
            documents=[Document(content="Patrick habite à Paris.")]
        )
        query_out = await query_component.run_async(query="Où est Patrick ?")

        # Extract the PERSON token from each
        doc_content = doc_out["documents"][0].content
        query_content = query_out["query"]
        doc_token_start = doc_content.index("<PERSON:")
        doc_token = doc_content[doc_token_start : doc_content.index(">", doc_token_start) + 1]
        query_token_start = query_content.index("<PERSON:")
        query_token = query_content[
            query_token_start : query_content.index(">", query_token_start) + 1
        ]
        assert doc_token == query_token

    async def test_scope_defaults_to_query(self, pipeline) -> None:
        component = PIIGhostQueryAnonymizer(pipeline=pipeline)
        out = await component.run_async(query="Patrick")
        # No exception — default scope works.
        assert "<PERSON:" in out["query"]

    def test_sync_run(self, pipeline) -> None:
        component = PIIGhostQueryAnonymizer(pipeline=pipeline)
        out = component.run(query="Où habite Patrick ?")
        assert "<PERSON:" in out["query"]
```

- [x] **Step 7.2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/haystack/test_query_anonymizer.py -v`
Expected: FAIL — `ImportError: cannot import name 'PIIGhostQueryAnonymizer'`

- [x] **Step 7.3: Implement `PIIGhostQueryAnonymizer`**

Append to `src/piighost/integrations/haystack/documents.py`:

```python
from piighost.models import Entity


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
    async def run_async(
        self, query: str, scope: str = "query"
    ) -> dict[str, Any]:
        anonymized, entities = await self._pipeline.anonymize(query, thread_id=scope)
        return {"query": anonymized, "entities": entities}

    @component.output_types(query=str, entities=list[Entity])
    def run(self, query: str, scope: str = "query") -> dict[str, Any]:
        return run_coroutine_sync(self.run_async(query=query, scope=scope))
```

- [x] **Step 7.4: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/haystack/test_query_anonymizer.py -v`
Expected: 5 tests PASS.

- [x] **Step 7.5: Commit**

```bash
git add src/piighost/integrations/haystack/documents.py tests/integrations/haystack/test_query_anonymizer.py
git commit -m "feat: add PIIGhostQueryAnonymizer haystack component"
```

---

## Task 8: `PIIGhostRehydrator`

**Files:**
- Modify: `src/piighost/integrations/haystack/documents.py` (append component)
- Create: `tests/integrations/haystack/test_rehydrator.py`

- [x] **Step 8.1: Write failing tests**

Create `tests/integrations/haystack/test_rehydrator.py`:

```python
"""Tests for ``PIIGhostRehydrator``."""

import json

import pytest
from haystack import Document

from piighost.exceptions import RehydrationError
from piighost.integrations.haystack.documents import (
    PIIGhostDocumentAnonymizer,
    PIIGhostRehydrator,
)

pytestmark = pytest.mark.asyncio


def _mapping(items: list[dict[str, str]]) -> str:
    return json.dumps(items)


class TestRoundtrip:
    """Anonymize → Rehydrate restores the original content."""

    async def test_full_roundtrip(self, pipeline) -> None:
        anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
        rehydrator = PIIGhostRehydrator()

        doc = Document(content="Patrick habite à Paris.")
        anon_out = await anonymizer.run_async(documents=[doc])
        rehydrated_out = await rehydrator.run_async(documents=anon_out["documents"])

        assert rehydrated_out["documents"][0].content == "Patrick habite à Paris."


class TestLenient:
    """Default lenient behaviour: missing mapping leaves content unchanged."""

    async def test_missing_mapping_passes_through(self) -> None:
        rehydrator = PIIGhostRehydrator()
        doc = Document(content="<PERSON:abc> habite à <LOCATION:def>.")
        out = await rehydrator.run_async(documents=[doc])
        assert out["documents"][0].content == "<PERSON:abc> habite à <LOCATION:def>."

    async def test_malformed_mapping_passes_through(self) -> None:
        rehydrator = PIIGhostRehydrator()
        doc = Document(
            content="<PERSON:abc>",
            meta={"piighost_mapping": "not valid json"},
        )
        out = await rehydrator.run_async(documents=[doc])
        assert out["documents"][0].content == "<PERSON:abc>"


class TestStrict:
    """``fail_on_missing_mapping=True`` raises RehydrationError."""

    async def test_strict_missing_mapping_raises(self) -> None:
        rehydrator = PIIGhostRehydrator(fail_on_missing_mapping=True)
        doc = Document(content="<PERSON:abc>")
        with pytest.raises(RehydrationError):
            await rehydrator.run_async(documents=[doc])

    async def test_strict_malformed_mapping_raises(self) -> None:
        rehydrator = PIIGhostRehydrator(fail_on_missing_mapping=True)
        doc = Document(
            content="<PERSON:abc>",
            meta={"piighost_mapping": "{bad json"},
        )
        with pytest.raises(RehydrationError):
            await rehydrator.run_async(documents=[doc])


class TestLongestFirst:
    """Replacement is longest-first to avoid partial-token collisions."""

    async def test_longest_token_replaced_first(self) -> None:
        rehydrator = PIIGhostRehydrator()
        mapping = _mapping(
            [
                {"token": "<X>", "original": "short", "label": "X"},
                {"token": "<X_EXTENDED>", "original": "longer", "label": "X"},
            ]
        )
        doc = Document(
            content="<X_EXTENDED> et <X>",
            meta={"piighost_mapping": mapping},
        )
        out = await rehydrator.run_async(documents=[doc])
        assert out["documents"][0].content == "longer et short"


class TestSyncRun:
    """Sync ``run()`` roundtrip."""

    def test_sync_roundtrip(self, pipeline) -> None:
        anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
        rehydrator = PIIGhostRehydrator()

        doc = Document(content="Patrick habite à Paris.")
        anon_out = anonymizer.run(documents=[doc])
        rehyd_out = rehydrator.run(documents=anon_out["documents"])
        assert rehyd_out["documents"][0].content == "Patrick habite à Paris."
```

- [x] **Step 8.2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/haystack/test_rehydrator.py -v`
Expected: FAIL — `ImportError: cannot import name 'PIIGhostRehydrator'`

- [x] **Step 8.3: Implement `PIIGhostRehydrator`**

Append to `src/piighost/integrations/haystack/documents.py`:

```python
from piighost.exceptions import RehydrationError


@component
class PIIGhostRehydrator:
    """Restore original content of Documents from their meta mapping.

    Reads ``meta[meta_key]`` as JSON, rebuilds the token → original map,
    and replaces tokens in ``content`` via ``str.replace`` (longest-first
    to avoid partial-token collisions).  No pipeline dependency — pure
    meta-driven.

    Args:
        fail_on_missing_mapping: If ``True``, raise ``RehydrationError``
            when a document has no mapping or a malformed one.  Default
            ``False`` — lenient pass-through with ``ERROR`` log.
        meta_key: Meta dict key that stores the JSON mapping.
    """

    def __init__(
        self,
        fail_on_missing_mapping: bool = False,
        meta_key: str = "piighost_mapping",
    ) -> None:
        self._fail_on_missing = fail_on_missing_mapping
        self._meta_key = meta_key

    @component.output_types(documents=list[Document])
    async def run_async(self, documents: list[Document]) -> dict[str, list[Document]]:
        for doc in documents:
            self._rehydrate(doc)
        return {"documents": documents}

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict[str, list[Document]]:
        return run_coroutine_sync(self.run_async(documents=documents))

    def _rehydrate(self, doc: Document) -> None:
        raw = doc.meta.get(self._meta_key)
        if raw is None:
            if self._fail_on_missing:
                raise RehydrationError(
                    f"Document {doc.id} has no mapping in meta[{self._meta_key!r}]",
                    partial_text=doc.content or "",
                )
            logger.error("doc %s missing mapping; content unchanged", doc.id)
            return

        try:
            mapping = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            if self._fail_on_missing:
                raise RehydrationError(
                    f"Document {doc.id} has malformed mapping: {exc}",
                    partial_text=doc.content or "",
                ) from exc
            logger.error("doc %s mapping malformed: %s", doc.id, exc)
            return

        if not isinstance(mapping, list) or doc.content is None:
            return

        # Longest-token-first, matches ThreadAnonymizationPipeline.deanonymize_with_ent.
        mapping.sort(key=lambda item: len(item.get("token", "")), reverse=True)

        content = doc.content
        for item in mapping:
            token = item.get("token")
            original = item.get("original")
            if not token or original is None:
                continue
            content = content.replace(token, original)
        doc.content = content
```

- [x] **Step 8.4: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/haystack/test_rehydrator.py -v`
Expected: 7 tests PASS.

- [x] **Step 8.5: Commit**

```bash
git add src/piighost/integrations/haystack/documents.py tests/integrations/haystack/test_rehydrator.py
git commit -m "feat: add PIIGhostRehydrator haystack component"
```

---

## Task 9: `PIIGhostDocumentClassifier` + presets

**Files:**
- Modify: `src/piighost/integrations/haystack/documents.py` (append component)
- Create: `src/piighost/integrations/haystack/presets.py`
- Create: `tests/integrations/haystack/test_document_classifier.py`
- Create: `tests/integrations/haystack/test_presets.py`

- [x] **Step 9.1: Write failing tests**

Create `tests/integrations/haystack/test_document_classifier.py`:

```python
"""Tests for ``PIIGhostDocumentClassifier``."""

import pytest
from haystack import Document

from piighost.classifier import ExactMatchClassifier
from piighost.integrations.haystack.documents import PIIGhostDocumentClassifier

pytestmark = pytest.mark.asyncio


@pytest.fixture
def classifier() -> ExactMatchClassifier:
    return ExactMatchClassifier(
        results={
            "Patient records for John": {
                "sensitivity": ["high"],
                "gdpr_category": ["health"],
                "language": ["en"],
            },
            "Recette de crêpes": {
                "sensitivity": ["low"],
                "gdpr_category": [],
                "language": ["fr"],
            },
        }
    )


class TestLabelsWritten:
    """Classifier populates ``meta[meta_key]`` with a structured dict."""

    async def test_writes_labels_as_dict(self, classifier) -> None:
        schemas = {
            "sensitivity": {"labels": ["low", "medium", "high"], "multi_label": False},
            "gdpr_category": {
                "labels": ["health", "financial", "none"],
                "multi_label": True,
            },
            "language": {"labels": ["en", "fr"], "multi_label": False},
        }
        component = PIIGhostDocumentClassifier(
            classifier=classifier, schemas=schemas
        )
        doc = Document(content="Patient records for John")
        out = await component.run_async(documents=[doc])
        labels = out["documents"][0].meta["labels"]
        assert labels == {
            "sensitivity": ["high"],
            "gdpr_category": ["health"],
            "language": ["en"],
        }

    async def test_content_not_modified(self, classifier) -> None:
        schemas = {"sensitivity": {"labels": ["low", "high"], "multi_label": False}}
        component = PIIGhostDocumentClassifier(
            classifier=classifier, schemas=schemas
        )
        doc = Document(content="Patient records for John")
        out = await component.run_async(documents=[doc])
        assert out["documents"][0].content == "Patient records for John"


class TestErrorHandling:
    """Lenient by default; strict re-raises."""

    async def test_lenient_error_writes_meta_error(self) -> None:
        class Boom:
            async def classify(self, text, schemas):
                raise RuntimeError("model oom")

        component = PIIGhostDocumentClassifier(
            classifier=Boom(),
            schemas={"x": {"labels": ["a"], "multi_label": False}},
        )
        doc = Document(content="hello")
        out = await component.run_async(documents=[doc])
        assert "piighost_classifier_error" in out["documents"][0].meta
        assert "labels" not in out["documents"][0].meta

    async def test_strict_reraises(self) -> None:
        class Boom:
            async def classify(self, text, schemas):
                raise RuntimeError("model oom")

        component = PIIGhostDocumentClassifier(
            classifier=Boom(),
            schemas={"x": {"labels": ["a"], "multi_label": False}},
            strict=True,
        )
        doc = Document(content="hello")
        with pytest.raises(RuntimeError, match="oom"):
            await component.run_async(documents=[doc])


class TestSyncRun:
    """Sync wrapper works."""

    def test_sync_run(self, classifier) -> None:
        schemas = {"sensitivity": {"labels": ["low", "high"], "multi_label": False}}
        component = PIIGhostDocumentClassifier(
            classifier=classifier, schemas=schemas
        )
        doc = Document(content="Patient records for John")
        out = component.run(documents=[doc])
        assert out["documents"][0].meta["labels"]["sensitivity"] == ["high"]
```

Create `tests/integrations/haystack/test_presets.py`:

```python
"""Tests for the GDPR / sensitivity / language presets."""

from piighost.integrations.haystack.presets import (
    PRESET_GDPR,
    PRESET_LANGUAGE,
    PRESET_SENSITIVITY,
)


class TestPresets:
    """Presets are well-formed ClassificationSchema dicts."""

    def test_gdpr_preset_has_expected_axes(self) -> None:
        assert "gdpr_category" in PRESET_GDPR
        schema = PRESET_GDPR["gdpr_category"]
        assert "health" in schema["labels"]
        assert "none" in schema["labels"]
        assert schema["multi_label"] is True

    def test_sensitivity_preset_is_single_label(self) -> None:
        schema = PRESET_SENSITIVITY["sensitivity"]
        assert schema["labels"] == ["low", "medium", "high"]
        assert schema["multi_label"] is False

    def test_language_preset_has_common_codes(self) -> None:
        schema = PRESET_LANGUAGE["language"]
        for code in ("fr", "en", "de"):
            assert code in schema["labels"]
```

- [x] **Step 9.2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/haystack/test_document_classifier.py tests/integrations/haystack/test_presets.py -v`
Expected: FAIL — `ImportError`s for missing component and presets module.

- [x] **Step 9.3: Implement presets**

Create `src/piighost/integrations/haystack/presets.py`:

```python
"""Ready-made classification schemas for common compliance use cases."""

from piighost.classifier.base import ClassificationSchema

PRESET_GDPR: dict[str, ClassificationSchema] = {
    "gdpr_category": {
        "labels": [
            "health",
            "financial",
            "biometric",
            "political",
            "children",
            "none",
        ],
        "multi_label": True,
    },
}

PRESET_SENSITIVITY: dict[str, ClassificationSchema] = {
    "sensitivity": {
        "labels": ["low", "medium", "high"],
        "multi_label": False,
    },
}

PRESET_LANGUAGE: dict[str, ClassificationSchema] = {
    "language": {
        "labels": ["fr", "en", "de", "es", "it", "nl"],
        "multi_label": False,
    },
}
```

- [x] **Step 9.4: Implement `PIIGhostDocumentClassifier`**

Append to `src/piighost/integrations/haystack/documents.py`:

```python
from piighost.classifier.base import AnyClassifier, ClassificationSchema


@component
class PIIGhostDocumentClassifier:
    """Classify Documents against named schemas and write labels to meta.

    Runs *before* the anonymizer so the classifier sees real text (it
    generally works worse on anonymized content).  Writes the result
    to ``meta[meta_key]`` as a structured ``dict[str, list[str]]`` —
    **not** JSON-serialized — so LanceDB can index the fields for
    filter-then-rank queries.

    Args:
        classifier: An implementation of the ``AnyClassifier`` protocol.
        schemas: Named classification axes.
        meta_key: Meta dict key for the result dict. Default ``"labels"``.
        strict: If ``True``, re-raise errors from the classifier.
    """

    def __init__(
        self,
        classifier: AnyClassifier,
        schemas: dict[str, ClassificationSchema],
        meta_key: str = "labels",
        strict: bool = False,
    ) -> None:
        self._classifier = classifier
        self._schemas = schemas
        self._meta_key = meta_key
        self._strict = strict

    @component.output_types(documents=list[Document])
    async def run_async(self, documents: list[Document]) -> dict[str, list[Document]]:
        for doc in documents:
            await self._classify(doc)
        return {"documents": documents}

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict[str, list[Document]]:
        return run_coroutine_sync(self.run_async(documents=documents))

    async def _classify(self, doc: Document) -> None:
        content = doc.content
        if content is None or not content.strip():
            return
        try:
            labels = await self._classifier.classify(content, self._schemas)
        except Exception as exc:
            if self._strict:
                raise
            logger.error("classification failed for doc %s: %s", doc.id, exc)
            doc.meta["piighost_classifier_error"] = type(exc).__name__
            return
        doc.meta[self._meta_key] = labels
```

- [x] **Step 9.5: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/haystack/test_document_classifier.py tests/integrations/haystack/test_presets.py -v`
Expected: 8 tests PASS.

- [x] **Step 9.6: Commit**

```bash
git add src/piighost/integrations/haystack/documents.py src/piighost/integrations/haystack/presets.py tests/integrations/haystack/test_document_classifier.py tests/integrations/haystack/test_presets.py
git commit -m "feat: add PIIGhostDocumentClassifier component and preset schemas"
```

---

## Task 10: `lancedb_meta_fields` helper

**Files:**
- Create: `src/piighost/integrations/haystack/lancedb.py`
- Create: `tests/integrations/haystack/test_lancedb_fields.py`

- [x] **Step 10.1: Write failing tests**

Create `tests/integrations/haystack/test_lancedb_fields.py`:

```python
"""Tests for the ``lancedb_meta_fields`` helper (no lancedb required)."""

import pyarrow as pa

from piighost.integrations.haystack.lancedb import lancedb_meta_fields
from piighost.integrations.haystack.presets import PRESET_SENSITIVITY


class TestWithoutSchemas:
    """Without classification schemas, all fields are plain strings."""

    def test_all_string_fields(self) -> None:
        fields = dict(lancedb_meta_fields())
        assert fields["piighost_mapping"] == pa.string()
        assert fields["piighost_profile"] == pa.string()
        assert fields["labels"] == pa.string()
        assert fields["piighost_error"] == pa.string()


class TestWithSchemas:
    """Schemas make ``labels`` a struct for filter-friendly indexing."""

    def test_labels_is_struct_with_schema_keys(self) -> None:
        fields = dict(lancedb_meta_fields(schemas=PRESET_SENSITIVITY))
        labels_type = fields["labels"]
        assert isinstance(labels_type, pa.StructType)
        names = {labels_type.field(i).name for i in range(labels_type.num_fields)}
        assert names == {"sensitivity"}
        assert labels_type.field("sensitivity").type == pa.list_(pa.string())

    def test_other_fields_still_string(self) -> None:
        fields = dict(lancedb_meta_fields(schemas=PRESET_SENSITIVITY))
        assert fields["piighost_mapping"] == pa.string()
        assert fields["piighost_profile"] == pa.string()

    def test_multiple_schemas_combine(self) -> None:
        from piighost.integrations.haystack.presets import PRESET_LANGUAGE

        fields = dict(
            lancedb_meta_fields(schemas={**PRESET_SENSITIVITY, **PRESET_LANGUAGE})
        )
        labels_type = fields["labels"]
        names = {labels_type.field(i).name for i in range(labels_type.num_fields)}
        assert names == {"sensitivity", "language"}
```

- [x] **Step 10.2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/haystack/test_lancedb_fields.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'piighost.integrations.haystack.lancedb'`

- [x] **Step 10.3: Implement the helper**

Create `src/piighost/integrations/haystack/lancedb.py`:

```python
"""Helper to build LanceDB-Haystack metadata schema fields.

LanceDB-Haystack enforces its metadata schema with PyArrow at store
creation time — unknown meta fields are rejected.  Users must declare
piighost's fields up front; this module provides a helper that does so
and, when classification schemas are provided, generates a struct type
for the ``labels`` meta field so it can be filtered on.
"""

import pyarrow as pa

from piighost.classifier.base import ClassificationSchema


def lancedb_meta_fields(
    schemas: dict[str, ClassificationSchema] | None = None,
) -> tuple[tuple[str, pa.DataType], ...]:
    """Return ``(name, pa.DataType)`` pairs to spread into a LanceDB schema.

    Example:
        >>> import pyarrow as pa
        >>> from piighost.integrations.haystack.lancedb import lancedb_meta_fields
        >>> from piighost.integrations.haystack.presets import PRESET_SENSITIVITY
        >>> metadata_schema = pa.struct([
        ...     ("title", pa.string()),
        ...     *lancedb_meta_fields(schemas=PRESET_SENSITIVITY),
        ... ])

    Args:
        schemas: Optional classification schemas used by
            ``PIIGhostDocumentClassifier``.  When provided, the returned
            ``labels`` field is a ``pa.struct`` with one ``list<string>``
            subfield per axis so LanceDB can filter on them.  When
            ``None``, ``labels`` is a plain ``pa.string()`` (JSON-encoded,
            not filterable).

    Returns:
        A tuple of ``(field_name, pa.DataType)`` pairs.
    """
    if schemas:
        labels_type: pa.DataType = pa.struct(
            [(name, pa.list_(pa.string())) for name in schemas]
        )
    else:
        labels_type = pa.string()

    return (
        ("piighost_mapping", pa.string()),
        ("piighost_profile", pa.string()),
        ("piighost_error", pa.string()),
        ("labels", labels_type),
    )
```

- [x] **Step 10.4: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/haystack/test_lancedb_fields.py -v`
Expected: 4 tests PASS.

- [x] **Step 10.5: Commit**

```bash
git add src/piighost/integrations/haystack/lancedb.py tests/integrations/haystack/test_lancedb_fields.py
git commit -m "feat: add lancedb_meta_fields helper for LanceDB-Haystack schema"
```

---

## Task 11: public exports + error-policy matrix test

**Files:**
- Modify: `src/piighost/integrations/haystack/__init__.py` (public exports)
- Create: `tests/integrations/haystack/test_error_policy.py`

- [x] **Step 11.1: Add public exports**

Replace `src/piighost/integrations/haystack/__init__.py`:

```python
"""Haystack integration for PIIGhost.

Install with: uv add piighost[haystack]
"""

import importlib.util

if importlib.util.find_spec("haystack") is None:
    raise ImportError(
        "You must install haystack to use the Haystack integration, "
        "please install piighost[haystack]"
    )

from piighost.integrations.haystack.documents import (
    PIIGhostDocumentAnonymizer,
    PIIGhostDocumentClassifier,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)
from piighost.integrations.haystack.lancedb import lancedb_meta_fields
from piighost.integrations.haystack.presets import (
    PRESET_GDPR,
    PRESET_LANGUAGE,
    PRESET_SENSITIVITY,
)

__all__ = [
    "PIIGhostDocumentAnonymizer",
    "PIIGhostDocumentClassifier",
    "PIIGhostQueryAnonymizer",
    "PIIGhostRehydrator",
    "PRESET_GDPR",
    "PRESET_LANGUAGE",
    "PRESET_SENSITIVITY",
    "lancedb_meta_fields",
]
```

- [x] **Step 11.2: Write error-policy matrix test**

Create `tests/integrations/haystack/test_error_policy.py`:

```python
"""Matrix test for lenient-vs-strict error behaviour across components."""

import pytest
from haystack import Document

from piighost.exceptions import RehydrationError
from piighost.integrations.haystack import (
    PIIGhostDocumentAnonymizer,
    PIIGhostDocumentClassifier,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)

pytestmark = pytest.mark.asyncio


class _BrokenDetector:
    async def detect(self, text):
        raise RuntimeError("detector down")


class _BrokenClassifier:
    async def classify(self, text, schemas):
        raise RuntimeError("classifier down")


@pytest.fixture
def broken_pipeline(pipeline):
    """Patch the fixture pipeline to use a broken detector."""
    pipeline._detector = _BrokenDetector()
    return pipeline


class TestDocumentAnonymizerErrors:
    async def test_lenient_writes_error_meta(self, broken_pipeline) -> None:
        component = PIIGhostDocumentAnonymizer(pipeline=broken_pipeline)
        doc = Document(content="Patrick")
        out = await component.run_async(documents=[doc])
        assert "piighost_error" in out["documents"][0].meta
        assert "piighost_mapping" not in out["documents"][0].meta

    async def test_strict_reraises(self, broken_pipeline) -> None:
        component = PIIGhostDocumentAnonymizer(pipeline=broken_pipeline, strict=True)
        doc = Document(content="Patrick")
        with pytest.raises(RuntimeError, match="detector down"):
            await component.run_async(documents=[doc])


class TestQueryAnonymizerStrictAlways:
    """QueryAnonymizer is always strict — PII-leak risk."""

    async def test_raises_on_error(self, broken_pipeline) -> None:
        component = PIIGhostQueryAnonymizer(pipeline=broken_pipeline)
        with pytest.raises(RuntimeError, match="detector down"):
            await component.run_async(query="Patrick")


class TestClassifierErrors:
    async def test_lenient_writes_classifier_error_meta(self) -> None:
        component = PIIGhostDocumentClassifier(
            classifier=_BrokenClassifier(),
            schemas={"x": {"labels": ["a"], "multi_label": False}},
        )
        doc = Document(content="hello")
        out = await component.run_async(documents=[doc])
        assert "piighost_classifier_error" in out["documents"][0].meta

    async def test_strict_reraises(self) -> None:
        component = PIIGhostDocumentClassifier(
            classifier=_BrokenClassifier(),
            schemas={"x": {"labels": ["a"], "multi_label": False}},
            strict=True,
        )
        doc = Document(content="hello")
        with pytest.raises(RuntimeError, match="classifier down"):
            await component.run_async(documents=[doc])


class TestRehydratorFailFlag:
    async def test_lenient_returns_unchanged(self) -> None:
        component = PIIGhostRehydrator()
        doc = Document(content="<PERSON:abc>")
        out = await component.run_async(documents=[doc])
        assert out["documents"][0].content == "<PERSON:abc>"

    async def test_strict_raises(self) -> None:
        component = PIIGhostRehydrator(fail_on_missing_mapping=True)
        doc = Document(content="<PERSON:abc>")
        with pytest.raises(RehydrationError):
            await component.run_async(documents=[doc])
```

- [x] **Step 11.3: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/haystack/test_error_policy.py -v`
Expected: 7 tests PASS.

- [x] **Step 11.4: Commit**

```bash
git add src/piighost/integrations/haystack/__init__.py tests/integrations/haystack/test_error_policy.py
git commit -m "feat: expose public haystack api and add error-policy matrix test"
```

---

## Task 12: end-to-end pipeline wiring test

**Files:**
- Create: `tests/integrations/haystack/test_pipeline_wiring.py`

- [x] **Step 12.1: Write the wiring test**

Create `tests/integrations/haystack/test_pipeline_wiring.py`:

```python
"""End-to-end test wiring the 4 Phase 1 components in a real Haystack Pipeline.

Uses ``InMemoryDocumentStore`` + ``InMemoryBM25Retriever`` so we don't
require LanceDB for the fast test suite.  Verifies the core promise:
anonymized ingest, hash-stable query tokens, and meta-driven rehydration.
"""

import pytest
from haystack import Document, Pipeline
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
from haystack.components.writers import DocumentWriter
from haystack.document_stores.in_memory import InMemoryDocumentStore

from piighost.classifier import ExactMatchClassifier
from piighost.integrations.haystack import (
    PIIGhostDocumentAnonymizer,
    PIIGhostDocumentClassifier,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)

pytestmark = pytest.mark.asyncio


class TestFullWiring:
    """Ingest → store → query → rehydrate with real Haystack Pipeline."""

    async def test_end_to_end_flow(self, pipeline) -> None:  # ThreadAnonymizationPipeline fixture
        store = InMemoryDocumentStore()

        classifier_double = ExactMatchClassifier(
            results={
                "Patrick habite à Paris.": {"sensitivity": ["low"]},
            }
        )

        # --- Ingest pipeline ---
        ingest = Pipeline()
        ingest.add_component(
            "classifier",
            PIIGhostDocumentClassifier(
                classifier=classifier_double,
                schemas={"sensitivity": {"labels": ["low", "high"], "multi_label": False}},
            ),
        )
        ingest.add_component(
            "anonymizer", PIIGhostDocumentAnonymizer(pipeline=pipeline)
        )
        ingest.add_component("writer", DocumentWriter(document_store=store))
        ingest.connect("classifier.documents", "anonymizer.documents")
        ingest.connect("anonymizer.documents", "writer.documents")

        doc = Document(content="Patrick habite à Paris.")
        ingest.run({"classifier": {"documents": [doc]}})

        # --- Verify store has anonymized content only ---
        stored = store.filter_documents()
        assert len(stored) == 1
        stored_content = stored[0].content
        assert "Patrick" not in stored_content
        assert "Paris" not in stored_content
        assert "<PERSON:" in stored_content
        assert stored[0].meta["labels"]["sensitivity"] == ["low"]
        assert "piighost_mapping" in stored[0].meta

        # --- Query pipeline ---
        query_pipe = Pipeline()
        query_pipe.add_component(
            "query_anon", PIIGhostQueryAnonymizer(pipeline=pipeline)
        )
        query_pipe.add_component(
            "retriever", InMemoryBM25Retriever(document_store=store)
        )
        query_pipe.add_component("rehydrator", PIIGhostRehydrator())
        query_pipe.connect("query_anon.query", "retriever.query")
        query_pipe.connect("retriever.documents", "rehydrator.documents")

        result = query_pipe.run({"query_anon": {"query": "Où habite Patrick ?"}})

        # --- Verify rehydration ---
        docs = result["rehydrator"]["documents"]
        assert len(docs) >= 1
        assert docs[0].content == "Patrick habite à Paris."
```

- [x] **Step 12.2: Run the test**

Run: `uv run pytest tests/integrations/haystack/test_pipeline_wiring.py -v`
Expected: 1 test PASS.

- [x] **Step 12.3: Run the whole haystack suite**

Run: `uv run pytest tests/integrations/haystack/ tests/classifier/ -v`
Expected: all previous tests still PASS (roughly 40 tests).

- [x] **Step 12.4: Lint**

Run: `make lint`
Expected: 0 errors.

- [x] **Step 12.5: Commit**

```bash
git add tests/integrations/haystack/test_pipeline_wiring.py
git commit -m "test: add end-to-end haystack pipeline wiring test"
```

---

## Task 13: LanceDB roundtrip test (gated, slow)

**Files:**
- Create: `tests/integrations/haystack/test_lancedb_roundtrip.py`
- Modify: `pyproject.toml` (add a `[tool.pytest.ini_options]` `markers` entry if not present)

- [x] **Step 13.1: Declare the `slow` marker (if not already present)**

Check current `pyproject.toml` `[tool.pytest.ini_options]`. If it only has `addopts`, extend it with a `markers` list:

```toml
[tool.pytest.ini_options]
addopts = "--cov=src/piighost"
markers = [
    "slow: tests that require optional heavy backends (LanceDB, real GLiNER2)",
]
asyncio_mode = "auto"
```

Note: `asyncio_mode = "auto"` is already implicit via `pytestmark` in existing tests; leave as-is if already set.

- [x] **Step 13.2: Write the roundtrip test**

Create `tests/integrations/haystack/test_lancedb_roundtrip.py`:

```python
"""LanceDB-Haystack roundtrip: verify PyArrow schema survives write/read.

Gated on the ``lancedb_haystack`` extra via ``importorskip``. Marked
``slow`` so it does not run in the default fast test suite.
"""

import pytest
import pyarrow as pa

lancedb_haystack = pytest.importorskip("lancedb_haystack")

from haystack import Document

from piighost.integrations.haystack import (
    PIIGhostDocumentAnonymizer,
    PIIGhostRehydrator,
    lancedb_meta_fields,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]


async def test_mapping_survives_lancedb_roundtrip(tmp_path, pipeline) -> None:
    store = lancedb_haystack.LanceDBDocumentStore(
        database=str(tmp_path / "lance.db"),
        table_name="test",
        metadata_schema=pa.struct([*lancedb_meta_fields()]),
    )

    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    rehydrator = PIIGhostRehydrator()

    doc = Document(content="Patrick habite à Paris.")
    anon_out = await anonymizer.run_async(documents=[doc])
    store.write_documents(anon_out["documents"])

    # Read back from the store
    read_back = store.filter_documents()
    assert len(read_back) == 1
    # Mapping survived
    assert "piighost_mapping" in read_back[0].meta

    # Rehydrate
    rehyd_out = await rehydrator.run_async(documents=read_back)
    assert rehyd_out["documents"][0].content == "Patrick habite à Paris."
```

- [x] **Step 13.3: Run only when the extra is installed**

Run: `uv run pytest tests/integrations/haystack/test_lancedb_roundtrip.py -v -m slow`
Expected: if `lancedb_haystack` is installed → PASS. Otherwise → SKIPPED via `importorskip`.

- [x] **Step 13.4: Verify default suite skips `slow`**

Run: `uv run pytest tests/integrations/haystack/ -v` (no `-m slow`)
Expected: `test_lancedb_roundtrip` is collected but skipped (marker not selected). All other tests PASS.

- [x] **Step 13.5: Commit**

```bash
git add tests/integrations/haystack/test_lancedb_roundtrip.py pyproject.toml
git commit -m "test: add LanceDB roundtrip test for piighost haystack integration"
```

---

## Task 14: final verification

- [x] **Step 14.1: Run the entire test suite**

Run: `uv run pytest -v`
Expected: all tests pass (existing + new).

- [x] **Step 14.2: Run lint/type-check**

Run: `make lint`
Expected: 0 errors.

- [x] **Step 14.3: Verify examples still work**

Run: `uv run python -c "import piighost.middleware; import piighost.integrations.haystack"`
Expected: both imports succeed.

- [x] **Step 14.4: Final commit if anything pending**

```bash
git status
# If clean, nothing to do.
# If lint autofixed formatting:
git add -u
git commit -m "style: apply ruff formatting"
```

---

## Self-Review Checklist

- Task 1 — extras + skeleton ✅ covers spec §4.3
- Task 2 — `RehydrationError` ✅ covers spec §8 strict-rehydration
- Task 3 — classifier protocol + test double ✅ covers spec §4.1, §5.5
- Task 4 — `Gliner2Classifier` ✅ covers spec §5.5
- Task 5 — sync/async bridge ✅ covers spec §3 sync/async decision
- Task 6 — `PIIGhostDocumentAnonymizer` ✅ covers spec §5.1
- Task 7 — `PIIGhostQueryAnonymizer` ✅ covers spec §5.2
- Task 8 — `PIIGhostRehydrator` ✅ covers spec §5.3
- Task 9 — `PIIGhostDocumentClassifier` + presets ✅ covers spec §5.4
- Task 10 — `lancedb_meta_fields` ✅ covers spec §5.6
- Task 11 — public exports + error-policy matrix ✅ covers spec §8
- Task 12 — full Haystack pipeline wiring ✅ covers spec §9.1 primary test
- Task 13 — LanceDB roundtrip ✅ covers spec §9.1 slow test
- Task 14 — final verification

Phase 2 (chat, detect-only) is deliberately out of scope for this plan per spec §6.

## Notes for executor

- Keep each task as one logical commit. If a test surfaces an unrelated bug in existing code, stop and ask — do not fold fixes into the integration commits.
- The `asyncio_mode = "auto"` pytest setting is not present in the current `pyproject.toml`. The existing tests use `pytestmark = pytest.mark.asyncio` at module level — keep that pattern in the new tests (it's already in the code samples above).
- If `make lint` complains about unused `Any` imports or similar, remove them. The samples above import a bit generously; trim to what's actually used.
