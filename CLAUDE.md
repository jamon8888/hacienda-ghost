# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PIIGhost (v0.7.0) is a GDPR-compliant PII anonymization system. It ships as both a Python library and a full proxy stack that intercepts LLM API calls (Anthropic), anonymizes PII in-flight, and deanonymizes responses before they reach the user. The proxy is the primary production deployment.

## Development Commands

```bash
uv sync                      # Install dependencies
make lint                    # Format (ruff), lint (ruff), type-check (pyrefly)
uv run pytest                # Run all tests
uv run pytest tests/test_anonymizer.py -k "test_name"  # Run a single test

# Safe on Windows (no model loading):
uv run pytest tests/proxy tests/unit tests/classifier tests/linker tests/ph_factory tests/resolver tests/vault

# Install tests (skip OS-level side-effects):
PIIGHOST_SKIP_TRUSTSTORE=1 PIIGHOST_SKIP_SERVICE=1 uv run pytest tests/install
```

## Windows Quirks

- Two venvs: `.venv` (Python 3.12, default), `.venv2` (Python 3.13)
- `conftest.py` auto-skips `tests/cli`, `tests/service`, `tests/benchmarks`, `tests/e2e`, `tests/daemon`, `tests/integrations`, `tests/pipeline`, `tests/detector`, `tests/scripts` on win32 — torch/sentence-transformers cause segfaults when loading model weights
- Proxy tests and unit tests are safe to run on Windows

## Architecture

### Proxy Stack (primary deployment)

`AnthropicUpstream` ← `build_app()` (Starlette) ← `piighost proxy run`

Routes: `GET /health`, `GET /piighost-probe` (unauthenticated interception check), `POST /v1/messages` (anonymize → forward → deanonymize), `/{path}` catch-all passthrough

Paused mode: creating `<vault>/paused` sentinel file disables anonymization without stopping the proxy. `piighost on/off` creates/removes this file.

Install modes:
- `light` — generates CA + leaf cert for `localhost`, writes `ANTHROPIC_BASE_URL=https://localhost:8443` to `~/.claude/settings.json`
- `strict` — same CA for `api.anthropic.com` + edits `/etc/hosts` (sentinel block) + registers background service (launchd / systemd / schtasks)
- `forward` — mitmproxy-based forward HTTPS proxy for clients that do not honor `ANTHROPIC_BASE_URL` (e.g. Claude Desktop). Client is configured with `HTTPS_PROXY=127.0.0.1:8443`. Coverage matrix in `src/piighost/proxy/forward/dispatch.py`; unknown endpoints fail-closed with HTTP 403. Run with `piighost proxy run --mode=forward`.

Vault: `~/.piighost/` runtime directory — proxy certs at `proxy/`, audit NDJSON at `audit/YYYY-MM/sessions.ndjson`, project DBs at `projects/`

Environment variables for testing:
- `PIIGHOST_SKIP_TRUSTSTORE=1` — skip OS trust store install
- `PIIGHOST_SKIP_SERVICE=1` — skip background service registration
- `PIIGHOST_DETECTOR=stub` — stub detector (no GLiNER2 load), used by proxy test fixtures

### 5-Stage Anonymization Pipeline

`AnonymizationPipeline` (`pipeline.py`) orchestrates: **Detect → Resolve Spans → Link Entities → Resolve Entities → Anonymize**

1. **Detect**: `AnyDetector` protocol `GlinerDetector` runs GLiNER2 NER, `ExactMatchDetector` for tests, `RegexDetector` for patterns, `CompositeDetector` to chain detectors
2. **Resolve Spans**: `AnySpanConflictResolver` protocol `ConfidenceSpanConflictResolver` keeps highest-confidence detection when spans overlap
3. **Link Entities**: `AnyEntityLinker` protocol `ExactEntityLinker` finds all occurrences via word-boundary regex (`_expand`) and groups them (`_group`). Also provides `link_entities()` for cross-message linking
4. **Resolve Entities**: `AnyEntityConflictResolver` protocol `MergeEntityConflictResolver` (union-find) or `FuzzyEntityConflictResolver` (Jaro-Winkler)
5. **Anonymize**: `AnyAnonymizer` protocol `Anonymizer` uses `AnyPlaceholderFactory` (`CounterPlaceholderFactory` for `<<PERSON_1>>` tags) and applies span-based replacement

### Conversation Layer

`ThreadAnonymizationPipeline` (`pipeline/thread.py`) extends the base pipeline with:
- **Thread isolation**: memory and cache are scoped per `thread_id` (passed to each method, defaults to `"default"`)
- `ConversationMemory` accumulates entities across messages per thread, deduplicated by `(text.lower(), label)`, with `_add_variant()` to track case variants (e.g. "France" / "france")
- `link_entities()` on `ExactEntityLinker` links entities across messages so that "patrick" in message 2 shares the same placeholder as "Patrick" in message 1
- `deanonymize_with_ent()` / `anonymize_with_ent()` string-based token replacement for any text
- aiocache for detector result and anonymization mapping caching (SHA-256 keyed, prefixed by thread_id)

### Middleware Integration

`PIIAnonymizationMiddleware` (`middleware.py`) extends LangChain's `AgentMiddleware`:
- Extracts `thread_id` from LangGraph config via `get_config()["configurable"]["thread_id"]`
- `abefore_model` anonymizes all messages before the LLM sees them via `pipeline.anonymize(text, thread_id=...)`
- `aafter_model` deanonymizes for user display (cache-based, with `CacheMissError` fallback to entity-based)
- `awrap_tool_call` deanonymizes tool args, executes tool, re-anonymizes result via `pipeline.anonymize()`

### Design Patterns

All pipeline stages use **protocols** (structural subtyping) for dependency injection, making components swappable and testable. Tests use `ExactMatchDetector` to avoid loading the real GLiNER2 model.

## Conventions

- **Commits**: Conventional Commits via Commitizen (`feat:`, `fix:`, `refactor:`, etc.)
- **Type checking**: PyReFly (not mypy)
- **Formatting/linting**: Ruff
- **Package manager**: uv (not pip)
- **Python**: 3.12+ (3.10–3.14 in classifiers)
- **Data models**: Frozen dataclasses for immutability (`Entity`, `Detection`, `Span`)
- **Proxy test fixtures**: `stub_vault` fixture in `tests/proxy/conftest.py` sets `PIIGHOST_DETECTOR=stub` and creates a minimal vault in `tmp_path`
- **Docs**: bilingual (EN + FR) via zensical — `make docs-watch` / `make docs-watch-fr`

## Example Application

An example LangGraph agent with PII middleware is available in `examples/graph/`. It includes Aegra deployment, FastAPI HTTP server, PostgreSQL, and Langfuse observability. See `examples/graph/README.md` for details.

## CLI Commands

| Command | Purpose |
|---------|---------|
| `piighost install [--mode=light|strict]` | Install proxy (light: `localhost` cert; strict: hosts-file redirect + service) |
| `piighost uninstall [--purge-ca] [--purge-vault]` | Reverse install |
| `piighost proxy run [--mode=light|forward] [--port N] [--cert F] [--key F]` | Start HTTPS proxy (light: Starlette/uvicorn; forward: mitmproxy CONNECT) |
| `piighost proxy logs [--tail N]` | Tail audit NDJSON |
| `piighost doctor [--probe]` | Health check; `--probe` does live DNS + HTTPS interception check |
| `piighost daemon start/stop/status` | Manage background daemon |
| `piighost index <path>` | Index documents into vault |
| `piighost query <text>` | RAG query against vault |
| `piighost vault list/search/stats` | Manage vault contents |
| `piighost projects list/create/delete` | Multi-project management |
| `piighost self-update` | Update piighost binary |

## Docker

`make up` starts the workstation profile (port-forwarded). `make up-server` for headless. `make up-sovereign` adds embedder + LLM stack. Secrets go in `docker/secrets/`.

## Ongoing Work (as of 2026-04-25)

- Phase 2 (strict mode) and Phase 3 (Cowork probe) are fully implemented
- `tests/proxy/test_paused_mode.py` is written but not yet committed — tests the `<vault>/paused` sentinel flag
- `src/piighost/proxy/server.py` has uncommitted changes
- **Phase 1 forward proxy** (`feat/forward-proxy-phase1` branch) is complete — mitmproxy-based CONNECT proxy for Claude Desktop; see `src/piighost/proxy/forward/` and plan at `docs/superpowers/plans/2026-04-25-forward-proxy-claude-desktop-phase1.md`
- Phases 2–5 (full API coverage, vault enrichment, Desktop wrapper, install/doctor) need separate plans
