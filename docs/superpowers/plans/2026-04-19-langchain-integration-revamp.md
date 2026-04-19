# LangChain Integration Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a document-pipeline LangChain integration for PIIGhost at feature-parity with the existing Haystack one — four components (anonymizer / classifier / rehydrator / query-anonymizer), presets, error-policy matrix, end-to-end wiring with `langchain-kreuzberg` loader + LanceDB vectorstore — while keeping the existing `piighost.middleware` agent path available.

**Architecture:** Extract `presets.py` from the Haystack subpackage up to `piighost.presets` so both integrations share it (BC re-export kept in Haystack). Build `piighost.integrations.langchain.transformers` containing four `BaseDocumentTransformer` subclasses (plus a `Runnable` for queries) that wrap `ThreadAnonymizationPipeline`. Move `piighost.middleware` into `piighost.integrations.langchain.middleware` with a BC re-export at the old path. Tests mirror the Haystack test suite (unit per component, error-policy matrix, end-to-end pipeline, gated LanceDB round-trip, gated KreuzbergLoader ingest).

**Tech Stack:** Python 3.10+, `langchain-core` (`BaseDocumentTransformer`, `Runnable`, `Document`), `langchain-community` (`LanceDB` vectorstore for the gated test), `langchain-kreuzberg` (`KreuzbergLoader`, gated), PIIGhost's `ThreadAnonymizationPipeline`, pytest + pytest-asyncio, ruff, pyrefly.

---

## File Structure

**Created:**
- `src/piighost/presets.py` — shared presets (moved from `integrations/haystack/presets.py`)
- `src/piighost/integrations/langchain/__init__.py` — public re-exports + `langchain` import guard
- `src/piighost/integrations/langchain/transformers.py` — 4 components (anonymizer, classifier, rehydrator, query)
- `src/piighost/integrations/langchain/middleware.py` — existing middleware moved here
- `tests/integrations/langchain/__init__.py`
- `tests/integrations/langchain/conftest.py` — fixtures (pipeline, test classifier)
- `tests/integrations/langchain/test_document_anonymizer.py`
- `tests/integrations/langchain/test_document_classifier.py`
- `tests/integrations/langchain/test_rehydrator.py`
- `tests/integrations/langchain/test_query_anonymizer.py`
- `tests/integrations/langchain/test_presets.py`
- `tests/integrations/langchain/test_error_policy.py`
- `tests/integrations/langchain/test_pipeline_wiring.py`
- `tests/integrations/langchain/test_lancedb_roundtrip.py` (gated/slow)
- `tests/integrations/langchain/test_kreuzberg_loader.py` (gated/slow)

**Modified:**
- `src/piighost/integrations/haystack/presets.py` — shrink to BC re-export from `piighost.presets`
- `src/piighost/middleware.py` — shrink to BC re-export from `piighost.integrations.langchain.middleware`
- `pyproject.toml` — add `langchain-lancedb` and `langchain-kreuzberg` extras; update `all`

---

## Task 1: Move presets to top-level module

**Why:** The three presets (GDPR / sensitivity / language) are framework-agnostic classification schemas — they will be imported by both the Haystack and LangChain classifier components. Keep a single source of truth.

**Files:**
- Create: `src/piighost/presets.py`
- Modify: `src/piighost/integrations/haystack/presets.py`
- Modify: `src/piighost/integrations/haystack/__init__.py` (verify re-exports still resolve)
- Test: `tests/integrations/haystack/test_presets.py` (unchanged, acts as BC check)

- [ ] **Step 1: Write failing test for new top-level import**

Create `tests/test_presets.py`:

```python
"""Top-level presets module is the single source of truth."""

from piighost.presets import PRESET_GDPR, PRESET_LANGUAGE, PRESET_SENSITIVITY


def test_gdpr_preset_shape() -> None:
    assert "gdpr_category" in PRESET_GDPR
    schema = PRESET_GDPR["gdpr_category"]
    assert set(schema["labels"]) >= {
        "health",
        "financial",
        "biometric",
        "political",
        "children",
        "none",
    }
    assert schema["multi_label"] is True


def test_sensitivity_preset_shape() -> None:
    schema = PRESET_SENSITIVITY["sensitivity"]
    assert schema["labels"] == ["low", "medium", "high"]
    assert schema["multi_label"] is False


def test_language_preset_shape() -> None:
    schema = PRESET_LANGUAGE["language"]
    assert set(schema["labels"]) >= {"fr", "en", "de", "es", "it", "nl"}
    assert schema["multi_label"] is False


def test_haystack_presets_are_same_objects() -> None:
    """BC: the Haystack re-export must be the identical dict object."""
    from piighost.integrations.haystack.presets import (
        PRESET_GDPR as HS_GDPR,
    )

    assert HS_GDPR is PRESET_GDPR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_presets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'piighost.presets'`.

- [ ] **Step 3: Create the top-level presets module**

Write `src/piighost/presets.py`:

```python
"""Ready-made classification schemas for common compliance use cases.

Framework-agnostic: consumed by every integration that exposes a
classifier component (Haystack, LangChain, future adapters). Edit here
only; integration subpackages re-export for import-path compatibility.
"""

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

__all__ = ["PRESET_GDPR", "PRESET_LANGUAGE", "PRESET_SENSITIVITY"]
```

- [ ] **Step 4: Shrink the Haystack presets module to a BC re-export**

Replace `src/piighost/integrations/haystack/presets.py` with:

```python
"""Backwards-compatible re-export. New code should import from ``piighost.presets``."""

from piighost.presets import PRESET_GDPR, PRESET_LANGUAGE, PRESET_SENSITIVITY

__all__ = ["PRESET_GDPR", "PRESET_LANGUAGE", "PRESET_SENSITIVITY"]
```

- [ ] **Step 5: Run both preset tests**

Run: `uv run pytest tests/test_presets.py tests/integrations/haystack/test_presets.py -v`
Expected: PASS — all preset shape + identity checks green.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff format src/piighost/presets.py src/piighost/integrations/haystack/presets.py tests/test_presets.py && uv run ruff check src/piighost/presets.py src/piighost/integrations/haystack/presets.py tests/test_presets.py && uv run pyrefly check src/piighost/presets.py`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/presets.py src/piighost/integrations/haystack/presets.py tests/test_presets.py
git commit -m "refactor(presets): promote schemas to piighost.presets

Shared across Haystack and upcoming LangChain integrations. Haystack
subpackage keeps a BC re-export so existing imports keep working."
```

---

## Task 2: Scaffold the langchain integration subpackage with import guard

**Why:** Mirror the Haystack subpackage: `from piighost.integrations.langchain import …` must raise a clear `ImportError` when the `langchain` extra is not installed, before any transformer class is touched.

**Files:**
- Create: `src/piighost/integrations/langchain/__init__.py`
- Create: `tests/integrations/langchain/__init__.py` (empty marker)
- Test: `tests/integrations/langchain/test_import_guard.py`

- [ ] **Step 1: Write failing test for the import guard**

Create `tests/integrations/langchain/test_import_guard.py`:

```python
"""The subpackage raises ImportError when langchain is missing."""

import importlib
import sys

import pytest


def test_import_raises_when_langchain_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate langchain not being installed.
    import importlib.util as util

    real_find = util.find_spec

    def fake_find(name: str, *args: object, **kwargs: object):
        if name == "langchain":
            return None
        return real_find(name, *args, **kwargs)

    monkeypatch.setattr(util, "find_spec", fake_find)
    sys.modules.pop("piighost.integrations.langchain", None)

    with pytest.raises(ImportError, match="piighost\\[langchain\\]"):
        importlib.import_module("piighost.integrations.langchain")


def test_import_succeeds_when_langchain_present() -> None:
    pytest.importorskip("langchain_core")
    sys.modules.pop("piighost.integrations.langchain", None)
    mod = __import__("piighost.integrations.langchain", fromlist=["*"])
    assert mod is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integrations/langchain/test_import_guard.py -v`
Expected: FAIL — subpackage does not exist yet.

- [ ] **Step 3: Create the subpackage init with guard**

Write `src/piighost/integrations/langchain/__init__.py`:

```python
"""LangChain integration for PIIGhost (document-pipeline components)."""

import importlib.util

if importlib.util.find_spec("langchain") is None:
    raise ImportError(
        "You must install langchain to use piighost.integrations.langchain, "
        "please install piighost[langchain]"
    )

__all__: list[str] = []
```

Write empty marker file `tests/integrations/langchain/__init__.py`:

```python
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integrations/langchain/test_import_guard.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/piighost/integrations/langchain/__init__.py tests/integrations/langchain/__init__.py tests/integrations/langchain/test_import_guard.py
git commit -m "feat(integrations/langchain): scaffold subpackage with import guard"
```

---

## Task 3: Shared conftest — pipeline & classifier fixtures

**Why:** All four component test modules need a reusable `ThreadAnonymizationPipeline` with a stubbed detector (deterministic, fast) and a stubbed `AnyClassifier`. Keep fixtures in one place so later tasks stay small.

**Files:**
- Create: `tests/integrations/langchain/conftest.py`

- [ ] **Step 1: Write the conftest**

Write `tests/integrations/langchain/conftest.py`:

```python
"""Fixtures shared by every LangChain integration test module."""

from __future__ import annotations

from typing import Any

import pytest

from piighost.classifier.base import AnyClassifier, ClassificationSchema
from piighost.detector.base import AnyDetector
from piighost.models import Detection, Entity
from piighost.pipeline.thread import ThreadAnonymizationPipeline
from piighost.placeholder import HashPlaceholderFactory


class _StubDetector:
    """Always returns a single PERSON entity covering the first occurrence of 'Alice'."""

    async def detect(self, text: str, *, thread_id: str) -> list[Entity]:
        idx = text.find("Alice")
        if idx < 0:
            return []
        return [
            Entity(
                label="PERSON",
                detections=[Detection(text="Alice", start=idx, end=idx + 5)],
            )
        ]


class _StubClassifier:
    """Returns fixed labels per schema."""

    def __init__(self, result: dict[str, list[str]]) -> None:
        self._result = result

    async def classify(
        self,
        text: str,
        schemas: dict[str, ClassificationSchema],
    ) -> dict[str, list[str]]:
        return {name: self._result.get(name, []) for name in schemas}


@pytest.fixture
def pipeline() -> ThreadAnonymizationPipeline:
    detector: AnyDetector = _StubDetector()  # type: ignore[assignment]
    return ThreadAnonymizationPipeline(
        detector=detector,
        ph_factory=HashPlaceholderFactory(),
    )


@pytest.fixture
def stub_classifier() -> AnyClassifier:
    return _StubClassifier({"gdpr_category": ["none"]})  # type: ignore[return-value]


@pytest.fixture
def gdpr_schemas() -> dict[str, ClassificationSchema]:
    from piighost.presets import PRESET_GDPR

    return PRESET_GDPR
```

- [ ] **Step 2: Sanity-check the fixtures wire together**

Run: `uv run pytest tests/integrations/langchain -v --collect-only`
Expected: collection succeeds (0 tests collected so far — just the guard + import module).

- [ ] **Step 3: Commit**

```bash
git add tests/integrations/langchain/conftest.py
git commit -m "test(integrations/langchain): shared pipeline & classifier fixtures"
```

---

## Task 4: Document anonymizer transformer

**Why:** First of the four components. Wraps `ThreadAnonymizationPipeline` as a `BaseDocumentTransformer` so any LangChain document pipeline (loader → splitter → this → vectorstore) can anonymize content in place and store the token→original mapping in `metadata["piighost_mapping"]`. Uses `doc.id or metadata["source"]` as `thread_id` to match Haystack semantics.

**Files:**
- Create: `src/piighost/integrations/langchain/transformers.py` (new; will grow across tasks 4–7)
- Test: `tests/integrations/langchain/test_document_anonymizer.py`

- [ ] **Step 1: Write the failing unit test**

Create `tests/integrations/langchain/test_document_anonymizer.py`:

```python
"""PIIGhostDocumentAnonymizer replaces content and writes mapping to metadata."""

import json

import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
)


@pytest.mark.asyncio
async def test_atransform_anonymizes_and_stores_mapping(pipeline) -> None:
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    docs = [Document(page_content="Hello Alice", metadata={"source": "doc-1"})]

    out = await anonymizer.atransform_documents(docs)

    assert len(out) == 1
    assert "Alice" not in out[0].page_content
    mapping = json.loads(out[0].metadata["piighost_mapping"])
    assert any(item["original"] == "Alice" for item in mapping)


def test_transform_sync_path(pipeline) -> None:
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    docs = [Document(page_content="Hello Alice", metadata={"source": "doc-2"})]

    out = anonymizer.transform_documents(docs)

    assert "Alice" not in out[0].page_content


def test_counter_factory_rejected(pipeline) -> None:
    from piighost.placeholder import CounterPlaceholderFactory

    pipeline.ph_factory = CounterPlaceholderFactory()
    with pytest.raises(ValueError, match="HashPlaceholderFactory"):
        PIIGhostDocumentAnonymizer(pipeline=pipeline)


def test_empty_content_is_skipped(pipeline) -> None:
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    docs = [Document(page_content="   ", metadata={"source": "doc-empty"})]

    out = anonymizer.transform_documents(docs)

    assert out[0].page_content == "   "
    assert "piighost_mapping" not in out[0].metadata
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integrations/langchain/test_document_anonymizer.py -v`
Expected: FAIL — `ImportError: cannot import name 'PIIGhostDocumentAnonymizer'`.

- [ ] **Step 3: Implement the anonymizer**

Write `src/piighost/integrations/langchain/transformers.py`:

```python
"""LangChain document-pipeline components for PIIGhost.

Four classes here:

* :class:`PIIGhostDocumentAnonymizer` — replaces ``page_content`` with
  anonymized text and writes a token→original JSON mapping to
  ``metadata[meta_key]``.
* :class:`PIIGhostDocumentClassifier` — (Task 5) writes labels to meta.
* :class:`PIIGhostRehydrator` — (Task 6) restores original content from
  the stored mapping.
* :class:`PIIGhostQueryAnonymizer` — (Task 7) a ``Runnable[str, dict]``
  for anonymizing query strings so they match indexed anonymized docs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Sequence

from langchain_core.documents import Document
from langchain_core.documents.transformers import BaseDocumentTransformer

from piighost.models import Entity
from piighost.pipeline.thread import ThreadAnonymizationPipeline
from piighost.placeholder import AnyPlaceholderFactory, CounterPlaceholderFactory

logger = logging.getLogger(__name__)


def _serialize_mapping(
    entities: list[Entity],
    ph_factory: AnyPlaceholderFactory,
) -> str:
    tokens = ph_factory.create(entities)
    items: list[dict[str, str]] = []
    for entity, token in tokens.items():
        for detection in entity.detections:
            items.append(
                {"token": token, "original": detection.text, "label": entity.label}
            )
    return json.dumps(items)


def _build_profile(entities: list[Entity]) -> dict[str, Any]:
    labels = sorted({e.label for e in entities})
    return {
        "has_person": any(e.label == "PERSON" for e in entities),
        "has_email": any("EMAIL" in e.label.upper() for e in entities),
        "has_location": any(e.label == "LOCATION" for e in entities),
        "n_entities": len(entities),
        "labels": labels,
    }


def _thread_id_for(doc: Document) -> str:
    if getattr(doc, "id", None):
        return str(doc.id)
    src = doc.metadata.get("source")
    return str(src) if src else "default"


class PIIGhostDocumentAnonymizer(BaseDocumentTransformer):
    """Anonymize LangChain Documents in place, storing the mapping in metadata.

    Args:
        pipeline: A configured ``ThreadAnonymizationPipeline``.
        populate_profile: Also write a JSON profile to ``metadata['piighost_profile']``.
        meta_key: Metadata key for the serialized mapping.
        strict: If ``True``, re-raise errors. Default is lenient (log ERROR,
            leave content unchanged, write ``metadata['piighost_error']``).
        allow_non_stable_tokens: Escape hatch for ``CounterPlaceholderFactory``.
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

    async def atransform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        for doc in documents:
            await self._process(doc)
        return list(documents)

    def transform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        return asyncio.run(self.atransform_documents(documents, **kwargs))

    async def _process(self, doc: Document) -> None:
        content = doc.page_content
        if content is None or not content.strip():
            logger.warning("Skipping doc %s: empty content", _thread_id_for(doc))
            return

        thread_id = _thread_id_for(doc)
        try:
            anonymized, entities = await self._pipeline.anonymize(
                content, thread_id=thread_id
            )
        except Exception as exc:
            if self._strict:
                raise
            logger.error("anonymization failed for %s: %s", thread_id, exc)
            doc.metadata["piighost_error"] = f"detection_failed:{type(exc).__name__}"
            return

        doc.page_content = anonymized
        doc.metadata[self._meta_key] = _serialize_mapping(
            entities, self._pipeline.ph_factory
        )
        if self._populate_profile:
            doc.metadata["piighost_profile"] = json.dumps(_build_profile(entities))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integrations/langchain/test_document_anonymizer.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint**

Run: `uv run ruff format src/piighost/integrations/langchain tests/integrations/langchain && uv run ruff check src/piighost/integrations/langchain tests/integrations/langchain`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/integrations/langchain/transformers.py tests/integrations/langchain/test_document_anonymizer.py
git commit -m "feat(integrations/langchain): document anonymizer transformer"
```

---

## Task 5: Document classifier transformer

**Why:** Classifier runs **before** the anonymizer on real content (classifiers perform worse on tokenized text). Writes `metadata["labels"]` as `dict[str, list[str]]` (not JSON) so LanceDB / downstream filters can index fields directly.

**Files:**
- Modify: `src/piighost/integrations/langchain/transformers.py` (append class)
- Test: `tests/integrations/langchain/test_document_classifier.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integrations/langchain/test_document_classifier.py`:

```python
"""PIIGhostDocumentClassifier writes structured labels to metadata."""

import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentClassifier,
)


@pytest.mark.asyncio
async def test_atransform_writes_labels_dict(stub_classifier, gdpr_schemas) -> None:
    classifier = PIIGhostDocumentClassifier(
        classifier=stub_classifier, schemas=gdpr_schemas
    )
    docs = [Document(page_content="Health record", metadata={"source": "d1"})]

    out = await classifier.atransform_documents(docs)

    assert out[0].metadata["labels"] == {"gdpr_category": ["none"]}


def test_sync_path(stub_classifier, gdpr_schemas) -> None:
    classifier = PIIGhostDocumentClassifier(
        classifier=stub_classifier, schemas=gdpr_schemas
    )
    docs = [Document(page_content="Health record", metadata={"source": "d2"})]

    out = classifier.transform_documents(docs)

    assert out[0].metadata["labels"]["gdpr_category"] == ["none"]


def test_empty_content_skipped(stub_classifier, gdpr_schemas) -> None:
    classifier = PIIGhostDocumentClassifier(
        classifier=stub_classifier, schemas=gdpr_schemas
    )
    docs = [Document(page_content="  ", metadata={"source": "d3"})]

    out = classifier.transform_documents(docs)

    assert "labels" not in out[0].metadata
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integrations/langchain/test_document_classifier.py -v`
Expected: FAIL — ImportError on `PIIGhostDocumentClassifier`.

- [ ] **Step 3: Append the classifier class**

Append to `src/piighost/integrations/langchain/transformers.py`:

```python
from piighost.classifier.base import AnyClassifier, ClassificationSchema


class PIIGhostDocumentClassifier(BaseDocumentTransformer):
    """Classify Documents and write structured labels to ``metadata[meta_key]``.

    Runs **before** the anonymizer so the classifier sees real text.

    Args:
        classifier: An implementation of the ``AnyClassifier`` protocol.
        schemas: Named classification axes.
        meta_key: Metadata key for the result dict. Default ``"labels"``.
        strict: If ``True``, re-raise classifier errors. Default is lenient
            (log ERROR, write ``metadata["classifier_error"]``).
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

    async def atransform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        for doc in documents:
            await self._process(doc)
        return list(documents)

    def transform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        return asyncio.run(self.atransform_documents(documents, **kwargs))

    async def _process(self, doc: Document) -> None:
        content = doc.page_content
        if content is None or not content.strip():
            logger.warning("Skipping classifier on empty content")
            return
        try:
            labels = await self._classifier.classify(content, self._schemas)
        except Exception as exc:
            if self._strict:
                raise
            logger.error("classification failed: %s", exc)
            doc.metadata["classifier_error"] = f"classify_failed:{type(exc).__name__}"
            return
        doc.metadata[self._meta_key] = labels
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integrations/langchain/test_document_classifier.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/piighost/integrations/langchain tests/integrations/langchain
uv run ruff check src/piighost/integrations/langchain tests/integrations/langchain
git add src/piighost/integrations/langchain/transformers.py tests/integrations/langchain/test_document_classifier.py
git commit -m "feat(integrations/langchain): document classifier transformer"
```

---

## Task 6: Rehydrator transformer

**Why:** Mirror of `PIIGhostRehydrator` from Haystack — pure metadata-driven replacement, no pipeline dependency. Needed so retrieved-and-reranked docs can be rehydrated before being handed to the user or a read-only LLM.

**Files:**
- Modify: `src/piighost/integrations/langchain/transformers.py` (append)
- Test: `tests/integrations/langchain/test_rehydrator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integrations/langchain/test_rehydrator.py`:

```python
"""PIIGhostRehydrator restores original content from metadata mapping."""

import json

import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402

from piighost.exceptions import RehydrationError  # noqa: E402
from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostRehydrator,
)


def _mapping(token: str, original: str, label: str = "PERSON") -> str:
    return json.dumps([{"token": token, "original": original, "label": label}])


def test_rehydrates_content() -> None:
    rehydrator = PIIGhostRehydrator()
    docs = [
        Document(
            page_content="Hello <PERSON:abc>",
            metadata={"piighost_mapping": _mapping("<PERSON:abc>", "Alice")},
        )
    ]

    out = rehydrator.transform_documents(docs)

    assert out[0].page_content == "Hello Alice"


def test_missing_mapping_lenient() -> None:
    rehydrator = PIIGhostRehydrator()
    docs = [Document(page_content="Hello <PERSON:abc>", metadata={})]

    out = rehydrator.transform_documents(docs)

    assert out[0].page_content == "Hello <PERSON:abc>"


def test_missing_mapping_strict_raises() -> None:
    rehydrator = PIIGhostRehydrator(fail_on_missing_mapping=True)
    docs = [Document(page_content="x", metadata={})]

    with pytest.raises(RehydrationError):
        rehydrator.transform_documents(docs)


def test_longest_token_first_no_partial_collision() -> None:
    rehydrator = PIIGhostRehydrator()
    raw = json.dumps(
        [
            {"token": "<PERSON:a>", "original": "Alice", "label": "PERSON"},
            {"token": "<PERSON:ab>", "original": "Alice Bob", "label": "PERSON"},
        ]
    )
    docs = [
        Document(
            page_content="see <PERSON:ab> and <PERSON:a>",
            metadata={"piighost_mapping": raw},
        )
    ]

    out = rehydrator.transform_documents(docs)

    assert out[0].page_content == "see Alice Bob and Alice"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integrations/langchain/test_rehydrator.py -v`
Expected: FAIL — `PIIGhostRehydrator` missing.

- [ ] **Step 3: Append the rehydrator class**

Append to `src/piighost/integrations/langchain/transformers.py`:

```python
from piighost.exceptions import RehydrationError


class PIIGhostRehydrator(BaseDocumentTransformer):
    """Restore original content from the JSON mapping in ``metadata[meta_key]``.

    Longest-token-first replacement avoids partial-token collisions.
    No pipeline dependency — pure meta-driven.

    Args:
        fail_on_missing_mapping: If ``True``, raise ``RehydrationError`` when
            mapping is absent or malformed. Default ``False`` (log ERROR, pass through).
        meta_key: Metadata key where the JSON mapping lives.
    """

    def __init__(
        self,
        fail_on_missing_mapping: bool = False,
        meta_key: str = "piighost_mapping",
    ) -> None:
        self._fail_on_missing = fail_on_missing_mapping
        self._meta_key = meta_key

    async def atransform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        for doc in documents:
            self._rehydrate(doc)
        return list(documents)

    def transform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        for doc in documents:
            self._rehydrate(doc)
        return list(documents)

    def _rehydrate(self, doc: Document) -> None:
        raw = doc.metadata.get(self._meta_key)
        if raw is None:
            if self._fail_on_missing:
                raise RehydrationError(
                    f"Document has no mapping in metadata[{self._meta_key!r}]",
                    partial_text=doc.page_content or "",
                )
            logger.error("doc missing mapping; content unchanged")
            return

        try:
            mapping = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            if self._fail_on_missing:
                raise RehydrationError(
                    f"Document has malformed mapping: {exc}",
                    partial_text=doc.page_content or "",
                ) from exc
            logger.error("doc mapping malformed: %s", exc)
            return

        if not isinstance(mapping, list) or doc.page_content is None:
            return

        mapping.sort(key=lambda item: len(item.get("token", "")), reverse=True)

        content = doc.page_content
        for item in mapping:
            token = item.get("token")
            original = item.get("original")
            if not token or original is None:
                continue
            content = content.replace(token, original)
        doc.page_content = content
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integrations/langchain/test_rehydrator.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/piighost/integrations/langchain tests/integrations/langchain
uv run ruff check src/piighost/integrations/langchain tests/integrations/langchain
git add src/piighost/integrations/langchain/transformers.py tests/integrations/langchain/test_rehydrator.py
git commit -m "feat(integrations/langchain): rehydrator transformer"
```

---

## Task 7: Query anonymizer as Runnable

**Why:** Queries are strings, not Documents — `BaseDocumentTransformer` doesn't fit. LangChain idiom for `str → something` is `Runnable`. Exposing it as `Runnable[str, dict[str, Any]]` makes it composable with `RunnablePassthrough`, LCEL chains, and retrievers. Strict by default: a silent failure would leak PII to the embedder.

**Files:**
- Modify: `src/piighost/integrations/langchain/transformers.py` (append)
- Test: `tests/integrations/langchain/test_query_anonymizer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integrations/langchain/test_query_anonymizer.py`:

```python
"""PIIGhostQueryAnonymizer is a Runnable[str, dict] and strict by default."""

import pytest

pytest.importorskip("langchain_core")

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostQueryAnonymizer,
)


def test_invoke_returns_query_and_entities(pipeline) -> None:
    anon = PIIGhostQueryAnonymizer(pipeline=pipeline)

    result = anon.invoke("Where is Alice?")

    assert "Alice" not in result["query"]
    assert any(e.label == "PERSON" for e in result["entities"])


@pytest.mark.asyncio
async def test_ainvoke_path(pipeline) -> None:
    anon = PIIGhostQueryAnonymizer(pipeline=pipeline)

    result = await anon.ainvoke("Where is Alice?")

    assert "Alice" not in result["query"]


def test_strict_raises_on_detector_failure(pipeline) -> None:
    class BrokenDetector:
        async def detect(self, text: str, *, thread_id: str):
            raise RuntimeError("boom")

    pipeline._detector = BrokenDetector()  # type: ignore[attr-defined]
    anon = PIIGhostQueryAnonymizer(pipeline=pipeline)

    with pytest.raises(RuntimeError, match="boom"):
        anon.invoke("Where is Alice?")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integrations/langchain/test_query_anonymizer.py -v`
Expected: FAIL — `PIIGhostQueryAnonymizer` missing.

- [ ] **Step 3: Append the Runnable**

Append to `src/piighost/integrations/langchain/transformers.py`:

```python
from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig


class PIIGhostQueryAnonymizer(Runnable[str, dict[str, Any]]):
    """Anonymize a query string; strict by default.

    Returns ``{"query": anonymized_str, "entities": list[Entity]}``.
    Because ``HashPlaceholderFactory`` is deterministic, the same entity
    produces the same token in a query as in an indexed document.
    """

    def __init__(
        self, pipeline: ThreadAnonymizationPipeline, scope: str = "query"
    ) -> None:
        self._pipeline = pipeline
        self._scope = scope

    def invoke(
        self,
        input: str,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return asyncio.run(self.ainvoke(input, config, **kwargs))

    async def ainvoke(
        self,
        input: str,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        anonymized, entities = await self._pipeline.anonymize(
            input, thread_id=self._scope
        )
        return {"query": anonymized, "entities": entities}
```

Also update the subpackage `__init__.py` to re-export the four classes:

Replace the body of `src/piighost/integrations/langchain/__init__.py` (after the import guard) with:

```python
from piighost.integrations.langchain.transformers import (
    PIIGhostDocumentAnonymizer,
    PIIGhostDocumentClassifier,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)
from piighost.presets import PRESET_GDPR, PRESET_LANGUAGE, PRESET_SENSITIVITY

__all__ = [
    "PIIGhostDocumentAnonymizer",
    "PIIGhostDocumentClassifier",
    "PIIGhostQueryAnonymizer",
    "PIIGhostRehydrator",
    "PRESET_GDPR",
    "PRESET_LANGUAGE",
    "PRESET_SENSITIVITY",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integrations/langchain/test_query_anonymizer.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Full lang-integration unit-test sweep**

Run: `uv run pytest tests/integrations/langchain -v --ignore=tests/integrations/langchain/test_lancedb_roundtrip.py --ignore=tests/integrations/langchain/test_kreuzberg_loader.py`
Expected: all preceding tests still green.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/integrations/langchain/transformers.py src/piighost/integrations/langchain/__init__.py tests/integrations/langchain/test_query_anonymizer.py
git commit -m "feat(integrations/langchain): query anonymizer Runnable + public re-exports"
```

---

## Task 8: Error-policy matrix test

**Why:** Lock the lenient-vs-strict behaviour across all four components into one cross-cutting test module, mirroring `tests/integrations/haystack/test_error_policy.py`. Catches regressions where one component silently changes its default.

**Files:**
- Test: `tests/integrations/langchain/test_error_policy.py`

- [ ] **Step 1: Write the matrix test**

Create `tests/integrations/langchain/test_error_policy.py`:

```python
"""Error-policy matrix for the four LangChain components."""

import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402

from piighost.classifier.base import ClassificationSchema  # noqa: E402
from piighost.exceptions import RehydrationError  # noqa: E402
from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
    PIIGhostDocumentClassifier,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)


class _BrokenDetector:
    async def detect(self, text: str, *, thread_id: str):
        raise RuntimeError("detector boom")


class _BrokenClassifier:
    async def classify(
        self, text: str, schemas: dict[str, ClassificationSchema]
    ) -> dict[str, list[str]]:
        raise RuntimeError("classifier boom")


@pytest.fixture
def broken_pipeline(pipeline):
    pipeline._detector = _BrokenDetector()  # type: ignore[attr-defined]
    return pipeline


class TestDocumentAnonymizerErrors:
    def test_lenient_default_writes_meta(self, broken_pipeline) -> None:
        anon = PIIGhostDocumentAnonymizer(pipeline=broken_pipeline)
        docs = [Document(page_content="Hello Alice", metadata={"source": "d1"})]
        out = anon.transform_documents(docs)
        assert out[0].metadata["piighost_error"].startswith("detection_failed:")
        assert out[0].page_content == "Hello Alice"

    def test_strict_reraises(self, broken_pipeline) -> None:
        anon = PIIGhostDocumentAnonymizer(pipeline=broken_pipeline, strict=True)
        docs = [Document(page_content="Hello Alice", metadata={"source": "d1"})]
        with pytest.raises(RuntimeError, match="detector boom"):
            anon.transform_documents(docs)


class TestQueryAnonymizerStrictAlways:
    def test_always_raises(self, broken_pipeline) -> None:
        anon = PIIGhostQueryAnonymizer(pipeline=broken_pipeline)
        with pytest.raises(RuntimeError, match="detector boom"):
            anon.invoke("Hello Alice")


class TestClassifierErrors:
    def test_lenient_writes_classifier_error(self) -> None:
        schemas: dict[str, ClassificationSchema] = {
            "x": {"labels": ["a"], "multi_label": False}
        }
        comp = PIIGhostDocumentClassifier(
            classifier=_BrokenClassifier(),  # type: ignore[arg-type]
            schemas=schemas,
        )
        docs = [Document(page_content="hi", metadata={})]
        out = comp.transform_documents(docs)
        assert out[0].metadata["classifier_error"].startswith("classify_failed:")

    def test_strict_reraises(self) -> None:
        schemas: dict[str, ClassificationSchema] = {
            "x": {"labels": ["a"], "multi_label": False}
        }
        comp = PIIGhostDocumentClassifier(
            classifier=_BrokenClassifier(),  # type: ignore[arg-type]
            schemas=schemas,
            strict=True,
        )
        docs = [Document(page_content="hi", metadata={})]
        with pytest.raises(RuntimeError, match="classifier boom"):
            comp.transform_documents(docs)


class TestRehydratorFailFlag:
    def test_lenient_returns_unchanged(self) -> None:
        r = PIIGhostRehydrator()
        docs = [Document(page_content="<PERSON:a>", metadata={})]
        out = r.transform_documents(docs)
        assert out[0].page_content == "<PERSON:a>"

    def test_strict_raises(self) -> None:
        r = PIIGhostRehydrator(fail_on_missing_mapping=True)
        docs = [Document(page_content="<PERSON:a>", metadata={})]
        with pytest.raises(RehydrationError):
            r.transform_documents(docs)
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/integrations/langchain/test_error_policy.py -v`
Expected: PASS (7 tests).

- [ ] **Step 3: Lint and commit**

```bash
uv run ruff format tests/integrations/langchain/test_error_policy.py
uv run ruff check tests/integrations/langchain/test_error_policy.py
git add tests/integrations/langchain/test_error_policy.py
git commit -m "test(integrations/langchain): error-policy matrix across components"
```

---

## Task 9: End-to-end pipeline test (no heavy backends)

**Why:** Lock in the intended wiring — classifier → anonymizer → vectorstore → query-anonymizer → retriever → rehydrator — using only in-memory components so the test is fast and always runs in CI. Mirrors `tests/integrations/haystack/test_pipeline_wiring.py`.

**Files:**
- Test: `tests/integrations/langchain/test_pipeline_wiring.py`

- [ ] **Step 1: Write the wiring test**

Create `tests/integrations/langchain/test_pipeline_wiring.py`:

```python
"""End-to-end LangChain wiring: classify → anonymize → index → query → rehydrate."""

import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
    PIIGhostDocumentClassifier,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)


class _InMemoryStore:
    """Minimal vectorstore stub: stores Documents, returns them on substring match."""

    def __init__(self) -> None:
        self.docs: list[Document] = []

    def add_documents(self, docs: list[Document]) -> None:
        self.docs.extend(docs)

    def similarity_search(self, query: str, k: int = 5) -> list[Document]:
        # substring match on page_content; copies so rehydration doesn't mutate store
        return [
            Document(page_content=d.page_content, metadata=dict(d.metadata))
            for d in self.docs
            if query in d.page_content
        ][:k]


@pytest.mark.asyncio
async def test_ingest_then_query_end_to_end(
    pipeline, stub_classifier, gdpr_schemas
) -> None:
    # Ingest: classify → anonymize → store
    classifier = PIIGhostDocumentClassifier(
        classifier=stub_classifier, schemas=gdpr_schemas
    )
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    store = _InMemoryStore()

    raw = [
        Document(page_content="Alice visited Paris.", metadata={"source": "doc-1"}),
    ]
    classified = await classifier.atransform_documents(raw)
    anonymized = await anonymizer.atransform_documents(list(classified))

    assert "Alice" not in anonymized[0].page_content
    assert anonymized[0].metadata["labels"] == {"gdpr_category": ["none"]}
    store.add_documents(list(anonymized))

    # Query: anonymize query → retrieve → rehydrate
    query_anon = PIIGhostQueryAnonymizer(pipeline=pipeline)
    rehydrator = PIIGhostRehydrator()

    qresult = await query_anon.ainvoke("Where did Alice go?")
    hits = store.similarity_search(qresult["query"], k=3)
    assert hits, "query token should match indexed token"

    rehydrated = await rehydrator.atransform_documents(hits)
    assert "Alice" in rehydrated[0].page_content
    assert "Paris" in rehydrated[0].page_content
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/integrations/langchain/test_pipeline_wiring.py -v`
Expected: PASS (1 test).

- [ ] **Step 3: Full fast-suite sanity check**

Run: `uv run pytest tests/integrations/langchain -v --ignore=tests/integrations/langchain/test_lancedb_roundtrip.py --ignore=tests/integrations/langchain/test_kreuzberg_loader.py`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/integrations/langchain/test_pipeline_wiring.py
git commit -m "test(integrations/langchain): end-to-end pipeline wiring"
```

---

## Task 10: Extras, gated LanceDB + Kreuzberg tests, middleware relocation

**Why:** Two gated integration tests prove the transformers compose with the real third-party loader (`langchain-kreuzberg`) and vectorstore (`langchain-community.LanceDB`). Pyproject extras declare the exact dependency sets users need. Middleware relocation finishes the subpackage layout without breaking existing imports.

**Files:**
- Modify: `pyproject.toml`
- Create: `src/piighost/integrations/langchain/middleware.py`
- Modify: `src/piighost/middleware.py` (shrink to BC re-export)
- Test: `tests/integrations/langchain/test_lancedb_roundtrip.py`
- Test: `tests/integrations/langchain/test_kreuzberg_loader.py`
- Test: `tests/test_middleware_bc.py` (new; verifies BC re-export)

- [ ] **Step 1: Add extras to pyproject**

Edit `pyproject.toml`, replace the `haystack-lancedb = [...]` block and `all = [...]` block with:

```toml
haystack-lancedb = [
    "piighost[haystack]",
    "lancedb-haystack>=0.1",
]
haystack-embeddings-local = [
    "piighost[haystack]",
    "sentence-transformers>=3.3",
]
haystack-embeddings-mistral = [
    "piighost[haystack]",
    "mistral-haystack>=0.1",
]
langchain-lancedb = [
    "piighost[langchain]",
    "langchain-community>=0.3",
    "lancedb>=0.15",
]
langchain-kreuzberg = [
    "piighost[langchain]",
    "langchain-kreuzberg>=0.1",
]
langchain-embeddings-local = [
    "piighost[langchain]",
    "langchain-huggingface>=0.2",
    "sentence-transformers>=3.3",
]
langchain-embeddings-mistral = [
    "piighost[langchain]",
    "langchain-mistralai>=0.2",
]
all = [
    "piighost[gliner2,langchain,faker,cache,client,spacy,transformers,llm,haystack]",
]
```

**Default embedding model:** `OrdalieTech/Solon-embeddings-base-0.1` — XLM-RoBERTa-base, 278M params, 1024-d, MIT license, MTEB-French 0.7306 (beats ada-002). Laptop-friendly on CPU (~30 ms/doc batched). GPU users can upgrade to `Solon-embeddings-large-0.1` (0.6B params, MTEB-FR 0.7490). **Must use `sentence-transformers` loader** (not raw `transformers`) because the HF config.json omits `model_type` (HF issue #42381). **Query prefix required:** `"query: "` — the query encoder expects it. Document encoder needs no prefix.

**Ordering invariant (document to pin in README):** anonymizer MUST run before the embedder. When wired correctly, a cloud embedder (Mistral) only ever sees `<PERSON:hash>` tokens — never raw PII. The token→original mapping stays local in LanceDB metadata.

- [ ] **Step 2: Move middleware into the langchain subpackage**

Run: `git mv src/piighost/middleware.py src/piighost/integrations/langchain/middleware.py`

Then create a BC shim at the old path — write `src/piighost/middleware.py`:

```python
"""Backwards-compatible re-export.

New code should import from ``piighost.integrations.langchain.middleware``.
"""

from piighost.integrations.langchain.middleware import (
    PIIAnonymizationMiddleware,
)

__all__ = ["PIIAnonymizationMiddleware"]
```

- [ ] **Step 3: BC test for middleware import path**

Create `tests/test_middleware_bc.py`:

```python
"""The legacy import path still resolves."""

import pytest

pytest.importorskip("langchain")


def test_legacy_path_still_exports_middleware() -> None:
    from piighost.middleware import PIIAnonymizationMiddleware
    from piighost.integrations.langchain.middleware import (
        PIIAnonymizationMiddleware as New,
    )

    assert PIIAnonymizationMiddleware is New
```

- [ ] **Step 4: Run fast test suite to confirm relocation didn't break anything**

Run: `uv run pytest tests/test_middleware_bc.py -v`
Expected: PASS.

- [ ] **Step 5: Write gated LanceDB roundtrip test**

Create `tests/integrations/langchain/test_lancedb_roundtrip.py`:

```python
"""Anonymize → embed (local Solon OR cloud Mistral) → LanceDB → query → rehydrate.

Parametrized over the two supported embedding backends. The Mistral branch also
asserts no raw PII is ever sent over the wire (the whole reason anonymizer must
run before the embedder).
"""

import os

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("lancedb")
pytest.importorskip("langchain_community")

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

from langchain_community.vectorstores import LanceDB  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)


def _make_embeddings(backend: str):
    if backend == "local":
        pytest.importorskip("sentence_transformers")
        pytest.importorskip("langchain_huggingface")
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(
            model_name="OrdalieTech/Solon-embeddings-base-0.1",
            encode_kwargs={"normalize_embeddings": True},
            query_encode_kwargs={"prompt": "query: "},
        )
    if backend == "mistral":
        pytest.importorskip("langchain_mistralai")
        if not os.getenv("MISTRAL_API_KEY"):
            pytest.skip("MISTRAL_API_KEY not set")
        from langchain_mistralai import MistralAIEmbeddings

        return MistralAIEmbeddings(model="mistral-embed")
    raise ValueError(f"unknown backend: {backend}")


@pytest.mark.parametrize("backend", ["local", "mistral"])
async def test_anonymize_index_query_rehydrate(backend, pipeline, tmp_path) -> None:
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    query_anon = PIIGhostQueryAnonymizer(pipeline=pipeline)
    rehydrator = PIIGhostRehydrator()
    embeddings = _make_embeddings(backend)

    raw = [
        Document(page_content="Alice visited Paris", metadata={"source": "a"}),
        Document(page_content="Bob stayed home", metadata={"source": "b"}),
    ]
    anonymized = await anonymizer.atransform_documents(raw)

    # Safety net: raw PII must be absent from page_content before the embedder
    # ever sees it (cloud case) — this is the core ordering invariant.
    for d in anonymized:
        assert "Alice" not in d.page_content
        assert "Paris" not in d.page_content

    db_path = str(tmp_path / "lancedb")
    store = LanceDB.from_documents(
        list(anonymized), embeddings, uri=db_path, table_name="piighost_test"
    )

    qresult = await query_anon.ainvoke("Where did Alice go?")
    assert "Alice" not in qresult["query"]
    hits = store.similarity_search(qresult["query"], k=2)
    assert hits, "retriever should return at least one hit"

    rehydrated = await rehydrator.atransform_documents(hits)
    joined = " ".join(d.page_content for d in rehydrated)
    assert "Alice" in joined
```

- [ ] **Step 5b: PII-leak assertion for the Mistral branch (mocked transport)**

Create `tests/integrations/langchain/test_mistral_no_leak.py`:

```python
"""Proof: when wired correctly, the Mistral embedder never sees raw PII.

Uses httpx.MockTransport to capture every outbound request body and asserts
that none of the original PII strings appear. This is the assertion the
ordering invariant hinges on — if the anonymizer is accidentally moved after
the embedder, this test fails loudly.
"""

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


async def test_no_raw_pii_in_outbound_request_body(pipeline) -> None:
    from langchain_mistralai import MistralAIEmbeddings

    captured: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(bytes(request.content))
        # Minimal plausible mistral-embed response — 1024-d zero vector per input.
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
    client = httpx.Client(transport=transport)
    async_client = httpx.AsyncClient(transport=transport)

    os.environ.setdefault("MISTRAL_API_KEY", "test-key")
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
        assert "Alice" not in text, "raw PII leaked to Mistral embedder"
        assert "Paris" not in text, "raw PII leaked to Mistral embedder"
```

- [ ] **Step 6: Write gated KreuzbergLoader ingest test**

Create `tests/integrations/langchain/test_kreuzberg_loader.py`:

```python
"""KreuzbergLoader → PIIGhostDocumentAnonymizer end-to-end."""

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langchain_kreuzberg")

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

from langchain_kreuzberg import KreuzbergLoader  # noqa: E402

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
)


async def test_loader_into_anonymizer(pipeline, tmp_path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("Alice visited Paris in April.", encoding="utf-8")

    loader = KreuzbergLoader(str(sample))
    docs = await loader.aload()
    assert docs and docs[0].page_content.strip()

    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    out = await anonymizer.atransform_documents(docs)

    assert "Alice" not in out[0].page_content
    assert "piighost_mapping" in out[0].metadata
    # Loader's own meta (source, mime_type, etc.) must be preserved.
    assert "source" in out[0].metadata
```

- [ ] **Step 7: Run the fast suite (gated tests skip if extras absent)**

Run: `uv run pytest tests/integrations/langchain -v -m "not slow"`
Expected: all fast langchain tests green; lancedb + kreuzberg tests not collected (no `-m slow`).

Run: `uv run pytest tests/integrations/langchain -v -m slow`
Expected: either PASS (if optional extras installed) or SKIPPED via `importorskip` — never fail.

- [ ] **Step 8: Full repo sanity check**

Run: `uv run pytest tests -v --ignore=tests/ph_factory --ignore=tests/test_middleware.py -m "not slow"`
Expected: no regressions from preset move / middleware relocation.

- [ ] **Step 9: Lint whole subpackage**

Run: `uv run ruff format src/piighost/integrations/langchain tests/integrations/langchain src/piighost/middleware.py && uv run ruff check src/piighost/integrations/langchain tests/integrations/langchain src/piighost/middleware.py && uv run pyrefly check src/piighost/integrations/langchain`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml src/piighost/middleware.py src/piighost/integrations/langchain/middleware.py tests/integrations/langchain/test_lancedb_roundtrip.py tests/integrations/langchain/test_kreuzberg_loader.py tests/integrations/langchain/test_mistral_no_leak.py tests/test_middleware_bc.py
git commit -m "feat(integrations/langchain): extras, gated LanceDB+Kreuzberg tests, middleware move

* Add 6 extras: langchain-lancedb, langchain-kreuzberg, langchain-embeddings-{local,mistral},
  haystack-embeddings-{local,mistral}
* Relocate PIIAnonymizationMiddleware into piighost.integrations.langchain.middleware
  with BC re-export at the old path
* Gated roundtrip test against real LanceDB vectorstore, parametrized over
  local (Solon-base via sentence-transformers) and cloud (mistral-embed) backends
* PII-leak proof test using httpx.MockTransport — asserts raw PII never reaches
  the Mistral API when anonymizer is wired before the embedder
* Gated ingest test using KreuzbergLoader"
```

---

## Task 11: Hybrid retrieval recipe (BM25 + vector)

**Why:** Pure vector retrieval on anonymized content degrades for PII-dominant queries ("Alain Dupont" → token is opaque, semantic similarity is weak). BM25 on `<PERSON:hash>` tokens is a perfect exact-match keyword because `HashPlaceholderFactory` is deterministic: the query-side token is byte-identical to the indexed token. An ensemble (BM25 + vector, RRF or weighted) recovers exact-name recall without losing semantic recall on non-PII queries. This task ships the recipe as an end-to-end test on the LangChain side (authoritative) and mirrors the pattern as a Haystack note (executed under Task 12).

**Files:**
- Test: `tests/integrations/langchain/test_hybrid_retrieval.py`

- [ ] **Step 1: Write the hybrid-retrieval E2E test**

Create `tests/integrations/langchain/test_hybrid_retrieval.py`:

```python
"""Hybrid retrieval (BM25 + vector) recovers exact-name recall on anonymized docs.

Scenario: a corpus contains three documents, only one mentions 'Alain Dupont'.
A query with the same name must rank that document first. Pure vector search
on anonymized tokens underperforms because <PERSON:hash> is opaque; BM25 on
the same token is exact. EnsembleRetriever combines the two.
"""

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langchain_community")
pytest.importorskip("rank_bm25")

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

from langchain.retrievers import EnsembleRetriever  # noqa: E402
from langchain_community.retrievers import BM25Retriever  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)


def _make_embeddings():
    pytest.importorskip("sentence_transformers")
    pytest.importorskip("langchain_huggingface")
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name="OrdalieTech/Solon-embeddings-base-0.1",
        encode_kwargs={"normalize_embeddings": True},
        query_encode_kwargs={"prompt": "query: "},
    )


async def test_bm25_plus_vector_recovers_exact_name(pipeline, tmp_path) -> None:
    from langchain_community.vectorstores import LanceDB

    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    query_anon = PIIGhostQueryAnonymizer(pipeline=pipeline)
    rehydrator = PIIGhostRehydrator()
    embeddings = _make_embeddings()

    raw = [
        Document(
            page_content="The legal brief mentions Alain Dupont as plaintiff.",
            metadata={"source": "case-1"},
        ),
        Document(
            page_content="Contract law overview: consideration and offer.",
            metadata={"source": "doctrine-1"},
        ),
        Document(
            page_content="Procedural deadlines for civil suits in France.",
            metadata={"source": "procedure-1"},
        ),
    ]
    anonymized = list(await anonymizer.atransform_documents(raw))
    for d in anonymized:
        assert "Alain" not in d.page_content

    # Vector leg
    db_path = str(tmp_path / "lancedb")
    vstore = LanceDB.from_documents(
        anonymized, embeddings, uri=db_path, table_name="hybrid"
    )
    vector_retriever = vstore.as_retriever(search_kwargs={"k": 3})

    # BM25 leg — exact keyword match on the opaque <PERSON:hash> token.
    bm25_retriever = BM25Retriever.from_documents(anonymized)
    bm25_retriever.k = 3

    ensemble = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.4, 0.6],
    )

    qresult = await query_anon.ainvoke("What does the brief say about Alain Dupont?")
    assert "Alain" not in qresult["query"], "query must be anonymized before retrieval"

    hits = await ensemble.ainvoke(qresult["query"])
    rehydrated = await rehydrator.atransform_documents(hits)

    assert rehydrated, "ensemble should return hits"
    top = rehydrated[0]
    assert "Alain Dupont" in top.page_content, (
        "hybrid retrieval must surface the exact-name document first"
    )
```

- [ ] **Step 2: Run the test (gated; skips if extras absent)**

Run: `uv run pytest tests/integrations/langchain/test_hybrid_retrieval.py -v -m slow`
Expected: PASS if `piighost[langchain-lancedb,langchain-embeddings-local]` + `rank_bm25` installed; SKIPPED otherwise.

- [ ] **Step 3: README recipe note**

Append to `README.md` under the LangChain integration section (one paragraph, no code block duplication — point at the test):

```markdown
### Hybrid retrieval for PII-heavy queries

When indexed content is anonymized, pure vector search can miss exact-name
lookups because placeholder tokens (`<PERSON:…>`) have no semantic content.
Combine BM25 (exact keyword match on the deterministic token) with vector
search using `EnsembleRetriever`. See
`tests/integrations/langchain/test_hybrid_retrieval.py` for a working recipe.

> **Ordering invariant.** The anonymizer must run before the embedder. When
> wired correctly, cloud embedders see only opaque tokens; the token→original
> mapping stays in LanceDB metadata on your infrastructure.
```

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff format tests/integrations/langchain/test_hybrid_retrieval.py
uv run ruff check tests/integrations/langchain/test_hybrid_retrieval.py
git add tests/integrations/langchain/test_hybrid_retrieval.py README.md
git commit -m "feat(integrations/langchain): hybrid retrieval recipe (BM25 + vector)

BM25 on deterministic <PERSON:hash> tokens recovers exact-name recall that
pure vector search on anonymized content loses. EnsembleRetriever combines
the two. End-to-end test proves 'Alain Dupont' lookup ranks the correct doc
first after anonymize → index → query → rehydrate."
```

---

## Task 12: Retrofit existing Haystack LanceDB test with real embeddings + hybrid recipe

**Why:** The existing `tests/integrations/haystack/test_lancedb_roundtrip.py` was written against fake embeddings (same shortcut as the pre-patched LangChain test). For feature parity with Task 10/11 on the LangChain side — and so Haystack users get the same PII-leak-proof guarantee and the same hybrid recipe — retrofit it. Use Haystack's native primitives: `SentenceTransformersDocumentEmbedder` (local Solon) and `MistralDocumentEmbedder` (cloud), plus `InMemoryBM25Retriever + InMemoryEmbeddingRetriever + DocumentJoiner(join_mode="reciprocal_rank_fusion")` for hybrid.

**Files:**
- Modify: `tests/integrations/haystack/test_lancedb_roundtrip.py`
- Create: `tests/integrations/haystack/test_mistral_no_leak.py`
- Create: `tests/integrations/haystack/test_hybrid_retrieval.py`

- [ ] **Step 1: Retrofit the roundtrip test with parametrized backends**

Edit `tests/integrations/haystack/test_lancedb_roundtrip.py` to mirror the LangChain pattern: remove the fake embeddings, add `@pytest.mark.parametrize("backend", ["local", "mistral"])`, gate each branch with `pytest.importorskip` and (for Mistral) `MISTRAL_API_KEY`. Use:

```python
if backend == "local":
    pytest.importorskip("sentence_transformers")
    from haystack.components.embedders import (
        SentenceTransformersDocumentEmbedder,
        SentenceTransformersTextEmbedder,
    )
    doc_embedder = SentenceTransformersDocumentEmbedder(
        model="OrdalieTech/Solon-embeddings-base-0.1",
        normalize_embeddings=True,
    )
    text_embedder = SentenceTransformersTextEmbedder(
        model="OrdalieTech/Solon-embeddings-base-0.1",
        prefix="query: ",
        normalize_embeddings=True,
    )
    doc_embedder.warm_up()
    text_embedder.warm_up()
else:
    pytest.importorskip("mistral_haystack")
    if not os.getenv("MISTRAL_API_KEY"):
        pytest.skip("MISTRAL_API_KEY not set")
    from mistral_haystack import MistralDocumentEmbedder, MistralTextEmbedder

    doc_embedder = MistralDocumentEmbedder(model="mistral-embed")
    text_embedder = MistralTextEmbedder(model="mistral-embed")
```

Keep the rest of the pipeline (anonymizer → embedder → LanceDB writer → query anonymizer → retriever → rehydrator) and assert that raw PII never appears in the anonymized `Document.content` values fed to the embedder.

- [ ] **Step 2: PII-leak proof for the Mistral Haystack branch**

Create `tests/integrations/haystack/test_mistral_no_leak.py` using the same `httpx.MockTransport` pattern as the LangChain version. If `MistralDocumentEmbedder` doesn't accept a custom httpx client, patch `mistral_haystack.MistralDocumentEmbedder._client` with `monkeypatch.setattr` to inject one, or use `respx` as a fallback (`pytest.importorskip("respx")`). Assert "Alice" and "Paris" never appear in any captured request body.

- [ ] **Step 3: Haystack hybrid retrieval recipe**

Create `tests/integrations/haystack/test_hybrid_retrieval.py` using `InMemoryDocumentStore` (avoids the LanceDB BM25 surface) wired as:

```python
from haystack import Pipeline
from haystack.components.joiners import DocumentJoiner
from haystack.components.retrievers.in_memory import (
    InMemoryBM25Retriever,
    InMemoryEmbeddingRetriever,
)

p = Pipeline()
p.add_component("bm25", InMemoryBM25Retriever(document_store=store, top_k=3))
p.add_component("vector", InMemoryEmbeddingRetriever(document_store=store, top_k=3))
p.add_component("text_embedder", text_embedder)
p.add_component("joiner", DocumentJoiner(join_mode="reciprocal_rank_fusion", top_k=3))
p.connect("text_embedder.embedding", "vector.query_embedding")
p.connect("bm25.documents", "joiner.documents")
p.connect("vector.documents", "joiner.documents")
```

Reuse the "Alain Dupont" corpus from Task 11 and assert the case-1 doc ranks first after rehydration.

- [ ] **Step 4: Run the Haystack slow suite**

Run: `uv run pytest tests/integrations/haystack/test_lancedb_roundtrip.py tests/integrations/haystack/test_mistral_no_leak.py tests/integrations/haystack/test_hybrid_retrieval.py -v -m slow`
Expected: PASS (with extras installed) or SKIPPED (without).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format tests/integrations/haystack
uv run ruff check tests/integrations/haystack
git add tests/integrations/haystack/test_lancedb_roundtrip.py tests/integrations/haystack/test_mistral_no_leak.py tests/integrations/haystack/test_hybrid_retrieval.py
git commit -m "test(integrations/haystack): real embeddings, PII-leak proof, hybrid retrieval

Parity with the LangChain integration:
* Roundtrip test parametrized over local (Solon-base) and cloud (mistral-embed)
* MockTransport-based proof that anonymizer-before-embedder keeps raw PII local
* BM25 + embedding retriever joined via RRF for exact-name recall on anonymized
  <PERSON:hash> tokens"
```
