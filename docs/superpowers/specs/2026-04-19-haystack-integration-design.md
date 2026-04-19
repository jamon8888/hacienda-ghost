# Haystack integration for PIIGhost

**Status:** Approved design
**Date:** 2026-04-19
**Author:** Brainstorming session with @emmanuel.mixtec

## 1. Goal

Add first-class [Haystack 2.x](https://haystack.deepset.ai/) support to PIIGhost so that sensitive documents and user queries can be anonymized before entering a RAG pipeline (typically `KreuzbergConverter → … → LanceDBDocumentStore`), and so retrieved documents can be rehydrated back to their original content for authorized display.

The integration mirrors the existing LangChain `PIIAnonymizationMiddleware` in spirit (reversible tokens, thread-scoped memory, opt-in dependency) but targets Haystack's component/socket model rather than LangGraph's agent hooks.

## 2. Context and constraints

### 2.1 Current state
- PIIGhost exposes an async `ThreadAnonymizationPipeline` (per-thread memory, reversible placeholders, aiocache).
- `PIIAnonymizationMiddleware` wraps it for LangChain/LangGraph agents.
- `PIIGhostClient` (HTTP) already straddles sync/async.

### 2.2 Haystack primitives
- Components use `@component`, `run()` and `@component.output_types(...)`. A `Pipeline` is a DAG connected by named sockets.
- `Document` is a mutable dataclass with `content: str | None` and `meta: dict`.
- Sync `Pipeline` calls `run()`; `AsyncPipeline` calls `run_async()`.

### 2.3 Kreuzberg
Single component `KreuzbergConverter`: input socket `sources` (paths / `ByteStream`), output socket `documents` (`list[Document]`). Covers 91+ file formats (PDF, DOCX, emails, archives, images with OCR).

### 2.4 LanceDB-Haystack
- `LanceDBDocumentStore` (embedded, in-process), `LanceDBEmbeddingRetriever`, `LanceDBFTSRetriever`, hybrid search.
- **Hard constraint:** metadata schema is a PyArrow `StructType`, declared up-front. **Unknown fields are rejected.** Any meta-embedded mapping must be a predeclared field.

### 2.5 Search-quality constraint
For an anonymized query to retrieve anonymized indexed content, the **same entity must produce the same token everywhere**. `CounterPlaceholderFactory` cannot guarantee this (counters reset per text). `HashPlaceholderFactory` already exists in PIIGhost and is deterministic (`"Patrick"` → `<PERSON:a4f7>` regardless of context).

## 3. Decisions (locked during brainstorming)

| Decision | Value | Rationale |
|----------|-------|-----------|
| Scope | Documents + Chat, phased | User wants both; docs first ships value for the Kreuzberg/LanceDB use case without blocking on chat |
| Mapping storage | `Document.meta["piighost_mapping"]` (default) | Zero-infra; travels with docs through splitters into the store |
| Mapping storage (future) | External vault via optional `MappingStore` protocol | Stubbed now, implemented later if needed |
| Default placeholder for doc components | `HashPlaceholderFactory` | Stable tokens across ingest and query — required for retrieval |
| Rehydration trust model | Trust-the-caller + split-pipelines pattern (library rehydrates unconditionally; docs show redacted-vs-clear split) | Simple; matches existing LangChain middleware; ACL belongs in the app |
| Ingest-time scope | Per-Document (use `doc.id` as `thread_id`) | Hash tokens already give cross-doc consistency; no shared memory needed |
| Chat-time scope | Explicit `thread_id` run-input on components | Mirrors LangChain middleware; no LangGraph runtime to rely on |
| Sync/async model | Ship both `run()` and `run_async()` | Sync path uses `asyncio.run`; raises clear `RuntimeError` if called inside a running loop |
| GLiNER2 leverage | Add classification-based doc labeling + PII profile in meta | Reuses loaded model; enables filter-then-rank in LanceDB |

## 4. Architecture

### 4.1 Package layout

```
src/piighost/
├── classifier/                                  # NEW — mirrors detector/
│   ├── __init__.py
│   ├── base.py                                  # AnyClassifier protocol
│   ├── gliner2.py                               # Gliner2Classifier (gated on gliner2 extra)
│   └── exact.py                                 # ExactMatchClassifier (test double)
└── integrations/
    ├── __init__.py
    └── haystack/
        ├── __init__.py                          # Public exports
        ├── _base.py                             # PipelineHolder mixin + sync/async bridge
        ├── documents.py                         # Phase 1: 4 components
        ├── presets.py                           # PRESET_GDPR, PRESET_SENSITIVITY, PRESET_LANGUAGE
        ├── lancedb.py                           # LANCEDB_META_FIELDS constant
        ├── chat.py                              # Phase 2 (stub in Phase 1)
        └── detect.py                            # Phase 2 (stub in Phase 1)
```

Existing `src/piighost/middleware.py` is **not modified** in this project; a future cleanup can move it to `integrations/langchain.py` with a re-export for back-compat.

### 4.2 Dependency gating

Each module guards its third-party import with `importlib.util.find_spec(...)` and raises a clear `ImportError` pointing at the correct extra, matching the existing `middleware.py` pattern.

### 4.3 `pyproject.toml` changes

```toml
[project.optional-dependencies]
haystack = ["haystack-ai>=2.8", "aiocache>=0.12"]
haystack-lancedb = ["piighost[haystack]", "lancedb-haystack>=0.1"]
# `all` grows to include `haystack`
```

## 5. Phase 1 — Document pipeline (shippable on its own)

### 5.1 `PIIGhostDocumentAnonymizer`

```python
@component
class PIIGhostDocumentAnonymizer:
    def __init__(
        self,
        pipeline: ThreadAnonymizationPipeline,
        populate_profile: bool = False,
        meta_key: str = "piighost_mapping",
        strict: bool = False,
        allow_non_stable_tokens: bool = False,  # escape hatch for CounterPlaceholderFactory
    ) -> None: ...

    @component.output_types(documents=list[Document])
    async def run_async(self, documents: list[Document]) -> dict: ...

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict: ...
```

**Behavior per document:**
1. If `doc.content` is empty or `None`: pass through unchanged, log `WARNING`.
2. Call `pipeline.anonymize(doc.content, thread_id=doc.id)`. Haystack `Document` auto-generates `id` at construction; we rely on that. If a caller passes a doc with an empty string id (pathological), fall back to `"default"` with a `WARNING`.
3. Overwrite `doc.content` with the anonymized string.
4. Serialize mapping (`list[{"token", "original", "label"}]`) to JSON and store in `doc.meta[meta_key]` as a **string**.
5. If `populate_profile=True`: write `doc.meta["piighost_profile"]` as a JSON string with booleans and counts derived from the returned entities (no extra model call).
6. On detector error: lenient path writes `meta["piighost_error"] = "detection_failed:<reason>"` and returns the original content; `strict=True` re-raises.

**Construction-time check:** if `pipeline._anonymizer.ph_factory` is a `CounterPlaceholderFactory` and `allow_non_stable_tokens=False`, raise `ValueError` with guidance to switch to `HashPlaceholderFactory`.

### 5.2 `PIIGhostQueryAnonymizer`

```python
@component
class PIIGhostQueryAnonymizer:
    def __init__(self, pipeline: ThreadAnonymizationPipeline) -> None: ...

    @component.output_types(query=str, entities=list[Entity])
    async def run_async(self, query: str, scope: str = "query") -> dict: ...

    @component.output_types(query=str, entities=list[Entity])
    def run(self, query: str, scope: str = "query") -> dict: ...
```

Calls `pipeline.anonymize(query, thread_id=scope)` and returns the anonymized string plus the entities (exposed so callers can log or forward to meta filters). **Strict by default:** any error raises. No silent pass-through — a silent failure here leaks real PII to the embedder.

### 5.3 `PIIGhostRehydrator`

```python
@component
class PIIGhostRehydrator:
    def __init__(
        self,
        fail_on_missing_mapping: bool = False,
        meta_key: str = "piighost_mapping",
    ) -> None: ...

    @component.output_types(documents=list[Document])
    async def run_async(self, documents: list[Document]) -> dict: ...

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict: ...
```

No pipeline dependency — pure meta-driven. For each document:
1. Read `doc.meta[meta_key]`; if missing → lenient pass-through or `RehydrationError` based on flag.
2. Parse JSON; if malformed → log `ERROR` with `doc.id`, lenient pass-through or raise.
3. Build `token → original` map, apply `str.replace` **longest-first** (matches `ThreadAnonymizationPipeline.deanonymize_with_ent`).
4. Overwrite `doc.content`.

`RehydrationError` is a new exception subclassing the existing `DeanonymizationError`.

### 5.4 `PIIGhostDocumentClassifier`

```python
@component
class PIIGhostDocumentClassifier:
    def __init__(
        self,
        classifier: AnyClassifier,
        schemas: dict[str, ClassificationSchema],
        meta_key: str = "labels",
        strict: bool = False,
    ) -> None: ...

    @component.output_types(documents=list[Document])
    async def run_async(self, documents: list[Document]) -> dict: ...

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict: ...
```

Writes `doc.meta[meta_key]` = `dict[schema_name, list[str]]` — a structured dict, **not** JSON-serialized (so LanceDB can index the fields for filter-then-rank queries). **Must run before the anonymizer** to see real text; wiring rule documented.

**Presets ship in `presets.py`:**
- `PRESET_GDPR` — `{"gdpr_category": {"labels": ["health", "financial", "biometric", "political", "children", "none"], "multi_label": True}}`
- `PRESET_SENSITIVITY` — `{"sensitivity": {"labels": ["low", "medium", "high"]}}`
- `PRESET_LANGUAGE` — `{"language": {"labels": ["fr", "en", "de", "es", "it", "nl"]}}`

### 5.5 `Gliner2Classifier` (new classifier subsystem)

Mirrors `Gliner2Detector`: takes an injected `GLiNER2` model, exposes `classify(text, schemas) -> dict[str, list[str]]`, calls `model.classify_text(...)`. Lives in `piighost/classifier/gliner2.py` and is gated on the existing `gliner2` extra. `ExactMatchClassifier` lives in `piighost/classifier/exact.py` for tests.

### 5.6 LanceDB helper

```python
# piighost/integrations/haystack/lancedb.py
import pyarrow as pa

def lancedb_meta_fields(
    schemas: dict[str, ClassificationSchema] | None = None,
) -> tuple[tuple[str, pa.DataType], ...]:
    """Return PyArrow fields to spread into a LanceDB metadata_schema."""
    ...
```

**Meta contract (source of truth):**

| Meta key | In-memory type | LanceDB PyArrow type |
|----------|---------------|----------------------|
| `piighost_mapping` | JSON-serialized `str` | `pa.string()` |
| `piighost_profile` | JSON-serialized `str` | `pa.string()` |
| `labels` | `dict[str, list[str]]` | `pa.struct([...])` derived from `schemas` |
| `piighost_error` | `str` (absent on success) | `pa.string()` nullable |

`piighost_mapping` and `piighost_profile` are always JSON strings (written by the components themselves, read+parsed by the `Rehydrator`). This keeps them schema-flexible without forcing users to pre-declare nested PyArrow types they'd never filter on.

`labels` is a real PyArrow struct so LanceDB users can do filter-then-rank queries like `labels.sensitivity == "low"`. When `schemas=None`, the helper falls back to `labels: pa.string()` (JSON-encoded) — functional but unfilterable.

Example:

```python
from piighost.integrations.haystack.lancedb import lancedb_meta_fields
from piighost.integrations.haystack.presets import PRESET_SENSITIVITY, PRESET_LANGUAGE
import pyarrow as pa

schemas = {**PRESET_SENSITIVITY, **PRESET_LANGUAGE}
metadata_schema = pa.struct([
    ("title", pa.string()),
    *lancedb_meta_fields(schemas=schemas),
])
```

## 6. Phase 2 — Chat + audit (shape confirmed, full spec follow-up)

- **`PIIGhostDocumentDetector`** — detect-only, populates `meta["piighost_entities"]`, never mutates `.content`. For compliance dashboards and DLP.
- **`PIIGhostChatAnonymizer`** / **`PIIGhostChatRehydrator`** — `list[ChatMessage] → list[ChatMessage]`, skip `TOOL` messages (tool wrapping handles those).
- **Tool-call hooks** — `piighost_tool_hooks(pipeline)` returns a `dict[str, Callable]` compatible with Haystack's `ToolInvoker(callbacks=...)`. Deanonymize args → run tool → re-anonymize result.

All three share Phase 1's `_base.py` `PipelineHolder` and sync/async bridge unchanged.

## 7. Data flow (end-to-end)

### 7.1 Ingest

```
KreuzbergConverter
  → PIIGhostDocumentClassifier     # meta["labels"] populated from real text
  → PIIGhostDocumentAnonymizer     # content replaced; meta["piighost_mapping"] set
  → DocumentSplitter               # meta (including mapping) copied to each chunk
  → SentenceTransformersDocumentEmbedder
  → DocumentWriter → LanceDBDocumentStore
```

The store holds only anonymized content plus mapping. Users SHOULD encrypt the `piighost_mapping` column at rest (library-external; documented, not enforced).

### 7.2 Query

```
User query
  → PIIGhostQueryAnonymizer        # same hash tokens as indexed content
  → SentenceTransformersTextEmbedder
  → LanceDBEmbeddingRetriever      # hybrid-search friendly via meta filters on `labels`
  → PIIGhostRehydrator             # restores .content from meta["piighost_mapping"]
  → PromptBuilder → ChatGenerator  # LLM sees rehydrated real content
  → user
```

### 7.3 Trust boundary

- **Store and retriever:** anonymized content only.
- **Everything past the Rehydrator:** real PII. Consumers are the trust zone.
- **Split-pipelines pattern:** docs will show a "redacted retrieval" variant that omits the Rehydrator for untrusted consumers.

## 8. Error handling policy

| Path | Default | Opt-in strict | Rationale |
|------|---------|---------------|-----------|
| `DocumentAnonymizer` | lenient + `meta["piighost_error"]` | `strict=True` | one bad doc ≠ ruined ingest |
| `DocumentClassifier` | lenient + `meta["piighost_classifier_error"]` | `strict=True` | labels are advisory |
| `QueryAnonymizer` | **strict** | — | silent failure would leak PII downstream |
| `Rehydrator` — missing mapping | lenient (content unchanged, tokens visible) | `fail_on_missing_mapping=True` | loud by design; tokens are visible to the caller |
| `Rehydrator` — malformed mapping | lenient + `ERROR` log | `fail_on_missing_mapping=True` | observability-grade, not pipeline-grade |
| Construction: bad placeholder factory | `ValueError` at init | `allow_non_stable_tokens=True` | fail-fast for an unrecoverable config mismatch |

## 9. Testing

### 9.1 Structure

```
tests/classifier/
├── test_exact_classifier.py
└── test_gliner2_classifier.py               # gated; marked `slow`

tests/integrations/haystack/
├── conftest.py                               # pipeline + ExactMatchDetector fixtures
├── test_document_anonymizer.py
├── test_query_anonymizer.py
├── test_rehydrator.py                        # roundtrip, missing, corrupted
├── test_document_classifier.py               # presets + multi_label
├── test_sync_async_bridge.py                 # run() vs run_async(); running-loop detection
├── test_error_policy.py                      # lenient vs strict matrix
├── test_pipeline_wiring.py                   # full Haystack Pipeline + InMemoryDocumentStore
└── test_lancedb_roundtrip.py                 # gated on lancedb_haystack; marked `slow`
```

### 9.2 Test doubles

- `ExactMatchDetector` (existing) avoids GLiNER2 in unit tests.
- `ExactMatchClassifier` (new) avoids GLiNER2 for classifier tests.
- `InMemoryDocumentStore` for the primary wiring test (no extra test deps).
- LanceDB gets its own `test_lancedb_roundtrip.py` that verifies the PyArrow schema round-trip with `LANCEDB_META_FIELDS`.

### 9.3 Non-goals

- GLiNER2 detection/classification quality (upstream's responsibility).
- Kreuzberg conversion correctness (upstream's responsibility; we only rely on the `list[Document]` contract).
- Haystack's pipeline graph mechanics.

### 9.4 CI

Default `uv run pytest` runs fast tests only. `uv run pytest -m slow` runs LanceDB + GLiNER2 tests. Matches the existing project style.

## 10. Out of scope

- External mapping vault (Redis/Postgres) — protocol stubbed only; full implementation deferred.
- Per-user ACL-based rehydration — belongs in the app layer.
- Relation extraction via GLiNER2 — high effort, deferred.
- Encryption of `piighost_mapping` at rest — documented guidance, not library-enforced.
- Haystack `AsyncPipeline` edge cases beyond the standard `run_async()` contract.

## 11. Open questions (post-approval)

None blocking. Resolve during plan writing:

- Exact fields of the `piighost_profile` JSON (booleans-and-counts vs richer statistics).
- Whether `presets.py` labels should be localized (FR/EN/DE) or English-only.
- Versioning strategy for the `piighost_mapping` JSON schema (add a leading `"version": 1` field now, or only when we first break the format).
