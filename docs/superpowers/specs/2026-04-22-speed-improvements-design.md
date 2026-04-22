# PIIGhost Speed Improvements — Design Spec

**Date:** 2026-04-22
**Scope:** Anonymization pipeline + document indexing path
**Target:** Both real-time single-message latency and conversation-thread throughput
**Deployment:** Mixed CPU/GPU, must degrade gracefully on CPU
**Conversation size:** Highly variable (unknown distribution)

---

## Background

PIIGhost's pipeline runs every message through five stages:

```
detect → resolve_spans → link_entities → resolve_entities → anonymize_text
```

Profiling estimates (no benchmark harness yet):

| Stage | Share of latency | Bottleneck |
|---|---|---|
| `detect` (GLiNER2 inference) | ~85% | Sequential single-text forward pass |
| `link_entities` (text expansion) | ~8% | Regex recompiled per detection |
| `resolve_entities` (conflict merge) | ~5% | O(n³) loop with list.pop() |
| `resolve_spans` | ~1% | Well-optimized (sort + greedy pass) |
| `anonymize_text` | ~1% | Python str.replace(), already fast |

No benchmark suite exists — improvements cannot currently be validated.

---

## Architecture

Three self-contained phases, each independently shippable:

```
Phase 1: Observability
  ├─ tests/benchmarks/           ← pytest-benchmark suite
  └─ pipeline instrumentation    ← OpenTelemetry spans per stage

Phase 2: Algorithmic Fixes  (the 15%)
  ├─ resolver/entity.py          ← O(n³) naive → Union-Find
  ├─ linker/entity.py            ← regex compiled per call → compiled once
  └─ detector/base.py            ← RegexDetector patterns compiled at __init__

Phase 3: Inference Acceleration  (the 85%)
  ├─ detector/gliner2.py         ← add batch_extract_entities() + quantize/compile/flash flags
  └─ pipeline/thread.py          ← add anonymize_batch() with asyncio.gather()
```

No breaking changes to any public API. New capabilities are opt-in via constructor args.

---

## Phase 1 — Observability

### Benchmark Suite (`tests/benchmarks/`)

Four benchmark modules, run with `uv run pytest tests/benchmarks/ --benchmark-autosave`.
Results saved to `.benchmarks/` for regression detection.

| File | What it measures |
|---|---|
| `bench_pipeline.py` | `anonymize()` end-to-end at 3 text sizes (50 / 500 / 2000 tokens), using `ExactMatchDetector` (no model load) |
| `bench_detector.py` | GLiNER2 inference latency on PII-dense texts (requires model) |
| `bench_resolver.py` | Entity resolver at 5, 20, 50 conflicting entities |
| `bench_linker.py` | Text expansion at 5, 15, 30 detections |

### OpenTelemetry Spans

Thin decorator wrapping each pipeline stage. Off by default (`PIIGHOST_TELEMETRY=true` to enable). Zero overhead when disabled. Works with any OTLP-compatible backend.

```
anonymize()
  ├─ span: detect           [ms, cache_hit=bool, n_detections]
  ├─ span: resolve_spans    [ms, n_detections]
  ├─ span: link_entities    [ms, n_entities]
  ├─ span: resolve_entities [ms, n_conflicts]
  └─ span: anonymize_text   [ms, n_replacements]
```

---

## Phase 2 — Algorithmic Fixes

### 1. Entity Resolver: Union-Find (`resolver/entity.py`)

**Current:** `MergeEntityConflictResolver.resolve()` uses a `while changed: for i: for j:` loop with `list.pop()`, which restarts the outer loop on every merge. Worst case: O(n³). For 50 conflicting entities this is ~125,000 iterations.

**Fix:** Replace with Union-Find (disjoint set) algorithm:
1. Single O(n²) pass to find all conflicting pairs → `union(i, j)`
2. Single O(n) pass to group by root → merged entities

Worst case drops to O(n² · α(n)) — effectively O(n²) with near-constant α. For 50 entities: ~2,500 iterations (~50x improvement). `MergeEntityConflictResolver` interface unchanged.

### 2. Entity Linker: Compile Patterns Once (`linker/entity.py`)

**Current:** `ExactEntityLinker._expand()` calls `find_all_word_boundary(text, detection.text)` which calls `re.compile()` on every invocation — one new compiled regex per detection per call.

**Fix:** Cache compiled patterns in `dict[str, re.Pattern]` keyed by entity text, populated on first encounter, reused thereafter. 2-line change. ~2-3x speedup for text expansion on repeated entities (common in conversation threads where the same name appears multiple times).

### 3. RegexDetector: Compile at `__init__` (`detector/base.py`)

**Current:** `RegexDetector.detect()` calls `re.compile(pattern)` inside the detection loop on every call.

**Fix:** Move compilation to `__init__` into `self._compiled: dict[str, re.Pattern]`. Zero behavior change. Eliminates recompilation on every message.

---

## Phase 3 — Inference Acceleration

GLiNER2 exposes native batch inference and several hardware acceleration flags. No ONNX support exists — CPU optimization is via `torch.compile` (inductor backend).

### 1. Batch Inference (`detector/gliner2.py`)

Add `detect_batch(texts: list[str]) -> list[list[Detection]]` to `Gliner2Detector`. Internally calls `model.batch_extract_entities(texts, labels, batch_size=self.batch_size)`.

- Constructor arg: `batch_size: int = 1` (default preserves current single-text behavior)
- GPU: 5-10x throughput improvement for conversation threads
- CPU: ~20-30% improvement from reduced Python/framework overhead

### 2. Hardware Acceleration Flags (`detector/gliner2.py`)

Three opt-in flags added to `Gliner2Detector.__init__()`, all defaulting to `False`:

| Flag | Effect | Hardware | Approx gain |
|---|---|---|---|
| `quantize=True` | fp16 quantization | GPU only | ~1.5x speed, ~2x memory reduction |
| `compile=True` | `torch.compile` fused kernels | GPU primary, CPU marginal | ~1.3x on GPU |
| `flash_attention=True` | Sets `USE_FLASHDEBERTA=1` before import | GPU only (requires `pip install flashdeberta`) | benchmark-dependent |

Combined on GPU with batching: expected 2-4x total throughput gain over current baseline.

`flash_attention=True` requires `flashdeberta` as an optional dependency — gated behind a clear error message if not installed.

### 3. Concurrent Batch Processing (`pipeline/base.py`)

Add `anonymize_batch(texts: list[str], thread_id: str = "default") -> list[tuple[str, list[Entity]]]` to `ThreadAnonymizationPipeline`:

1. Call `detector.detect_batch(texts)` — one batched model forward pass
2. Run resolver/linker/anonymizer per text via `asyncio.gather()` — concurrent but CPU-bound (fast after Phase 2 fixes)
3. Return results in input order

Existing `anonymize()` unchanged. Middleware and MCP server can adopt `anonymize_batch()` where they process multiple messages.

**Document indexing path:** The indexer processes documents by chunking them and running each chunk through `anonymize()`. Adopting `anonymize_batch()` here gives the same batching gains as the conversation path — no separate indexer changes needed beyond the call site.

### 4. Cache Eviction (`pipeline/thread.py`)

Add to `ThreadAnonymizationPipeline.__init__()`:
- `max_entities: int = 1000` — per-thread entity cap (LRU eviction)
- `max_threads: int = 100` — total thread cap (LRU eviction of least-recently-used thread)

Prevents unbounded memory growth in long-running deployments. Both default to generous values so existing behavior is unchanged for typical usage.

---

## Error Handling

- `flash_attention=True` without `flashdeberta` installed → `ImportError` with clear message at construction time, not at inference time
- `quantize=True` on CPU → log warning, skip quantization silently
- `compile=True` on CPU → applies torch inductor backend (no error, marginal benefit)
- `detect_batch()` with `batch_size=1` → degrades to sequential single-text calls (safe default)
- Cache eviction → evicted entities fall back to `deanonymize_with_ent()` (existing fallback path)

---

## Testing

- All Phase 2 fixes: correctness verified by existing test suite (no behavior change)
- Phase 3 batch inference: new unit tests asserting `detect_batch([text])[0] == detect(text)` for equivalence
- Phase 3 `anonymize_batch`: new tests asserting batch results match sequential results
- Benchmark suite (Phase 1) validates that each phase actually improves numbers before merging

---

## Delivery Order

```
Phase 1 → Phase 2 → Phase 3
```

Each phase is a separate PR. Phase 2 PRs can open while Phase 1 benchmark baselines are still being established, but Phase 3 should not merge until Phase 1 benchmarks are running and Phase 2 gains are confirmed.

---

## Out of Scope

- Replacing `RegexDetector` with GLiNER2's built-in `RegexValidator` (separate refactor)
- Multi-process parallelism (worker pools) — adds operational complexity
- Model fine-tuning / LoRA adapters
- Cloud API fallback (`GLiNER2.from_api()`)
