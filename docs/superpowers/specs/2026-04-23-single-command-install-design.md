# Single-Command Install — Design Spec

**Date:** 2026-04-23  
**Status:** Approved  
**Audience:** End users (non-technical) and developers  
**Platforms:** Windows, macOS  

---

## Goal

A single copy-paste command installs the full piighost MCP backend, downloads all models, and registers the MCP server in Claude Desktop — with an interactive progress bar and no manual steps.

```bash
# macOS / Linux
curl -LsSf https://piighost.dev/install.sh | sh

# Windows (PowerShell)
irm https://piighost.dev/install.ps1 | iex
```

Both scripts are thin bootstraps (no more than 50 lines). All real logic lives in a Python `piighost install` subcommand.

---

## Architecture

```
install.sh / install.ps1          (scripts/ — hosted at piighost.dev/install.*)
        │
        ├── ensure uv is installed (platform one-liner)
        └── uv run --from piighost piighost install --full
                        │
                ┌───────┴────────┐
                │                │
         Docker path          uv path
         (docker CLI           (always available)
          reachable)
                │                │
         docker compose       uv tool install
         pull + up -d         piighost[mcp,index,gliner2]
                │                │
                └───────┬────────┘
                        │
              model warm-up step
              (GLiNER2 base + adapter, Solon embedder)
                        │
              write claude_desktop_config.json
              (merge piighost mcpServers entry)
                        │
              "ready — restart Claude Desktop"
```

---

## New Files

```
src/piighost/install/
├── __init__.py       <- Typer command: piighost install [--full] [--dry-run] [--no-docker] [--reranker] [--force]
├── preflight.py      <- disk space, internet, Python version checks
├── docker.py         <- docker info detection, compose pull + up, healthcheck polling
├── uv_path.py        <- uv tool install subprocess call, upgrade detection
├── models.py         <- eager warm-up: GLiNER2 base + LoRA adapter + Solon embedder
├── claude_config.py  <- locate + merge claude_desktop_config.json, backup
└── ui.py             <- rich Console + Progress wrappers, step printer

scripts/
├── install.sh        <- curl | sh target: installs uv then calls piighost install --full
└── install.ps1       <- irm | iex target: same for Windows PowerShell
```

`piighost install` is registered as a new Typer subcommand in `cli/main.py`. Nothing changes in the MCP server, daemon, or existing CLI commands.

---

## Install Flow (Step by Step)

### Step 1 — Pre-flight checks
- Python >= 3.10 present (uv guarantees this)
- Disk space >= 2 GB free (warn prominently; `--force` overrides)
- Internet reachable (HuggingFace + PyPI ping)

### Step 2 — Docker detection
- Run `docker info` silently
- If reachable: Docker path (Step 3a)
- If not found or daemon not running: uv path (Step 3b), print reason

### Step 3a — Docker path
- Write `.env` from defaults if missing
- `docker compose -f docker-compose.yml -f docker-compose.embedder.yml pull`
- `docker compose ... up -d`
- Poll healthchecks every 5 s, timeout 3 min

### Step 3b — uv path
- `uv tool install "piighost[mcp,index,gliner2]" --python 3.12`
- Upgrades in-place if already installed

### Step 4 — Model warm-up (both paths)

Downloads via HuggingFace Hub with `rich` progress bars:

| Role | Download | Notes |
|------|----------|-------|
| NER base | `fastino/gliner2-large-v1` | ~500 MB |
| NER adapter | `jamon8888/french-pii-legal-ner-quantized` / `adapter_weights_int8.pt` | ~50 MB (INT8 LoRA) |
| Vector embeddings | `OrdalieTech/Solon-embeddings-base-0.1` | ~1.1 GB |
| Reranker (opt-in) | `BAAI/bge-reranker-base` | ~400 MB; only with `--reranker` flag |

Loading sequence for the French NER model (factored from `scripts/test_french_model.py` into `install/models.py`):
1. `GLiNER2.from_pretrained("fastino/gliner2-large-v1")`
2. `apply_lora_to_model(model, LoRAConfig(r=16, alpha=32))`
3. `torch.quantization.quantize_dynamic(model, {Linear}, dtype=qint8, inplace=True)`
4. `hf_hub_download("jamon8888/french-pii-legal-ner-quantized", "adapter_weights_int8.pt")`
5. `model.load_state_dict(state_dict)` then set model to inference mode

Models are cached to `~/.cache/huggingface/` (standard HF location). Warm-up is resumable — interrupted downloads restart from where they stopped.

The installer reads the configured model name from `.piighost/config.toml` if present, rather than hardcoding model names.

### Step 5 — Claude Desktop config registration

**Config paths by platform:**

| Platform | Path |
|----------|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

**uv path — MCP entry written:**
```json
"piighost": {
  "type": "stdio",
  "command": "uvx",
  "args": ["--from", "piighost[mcp,index,gliner2]", "piighost", "serve", "--transport", "stdio"],
  "env": { "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8" }
}
```

**Docker path — MCP entry written:**
```json
"piighost": {
  "type": "sse",
  "url": "http://localhost:8080/sse"
}
```

Config is merged non-destructively. A `.bak` backup is written before any modification.

### Step 6 — Done
- Print summary: path used, model cache sizes, config path modified
- "Restart Claude Desktop to activate piighost"

---

## CLI Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--full` | off | Download all models (required for full bundle) |
| `--dry-run` | off | Print every action without executing |
| `--no-docker` | off | Force uv path even if Docker is present |
| `--reranker` | off | Also warm up `BAAI/bge-reranker-base` |
| `--force` | off | Overwrite existing Claude Desktop config entry; proceed despite low disk |

All steps are idempotent — safe to re-run after a partial failure.

---

## Error Handling

### Pre-flight failures
- No internet: abort with "Cannot reach HuggingFace/PyPI. Check connection or set HTTPS_PROXY."
- Disk < 2 GB free: warn, require `--force` to proceed
- Python < 3.10: abort with "Python 3.10+ required. Run: `uv python install 3.12`"

### Docker path failures
- Docker found but daemon not running: auto-fallback to uv path
- `docker compose pull` fails: abort, show compose error, suggest `--no-docker`

### uv path failures
- uv not found (only possible when `piighost install` is called directly, not via bootstrap scripts which pre-install uv): print manual install URL, exit gracefully
- `uv tool install` fails: print pip fallback `pip install "piighost[mcp,index,gliner2]"`

### Model warm-up failures
- HuggingFace download interrupted: partial cache stays; re-run resumes
- `adapter_weights_int8.pt` load fails: clear error naming which step and which package is missing
- Slow download: progress bar with ETA, Ctrl+C cancels cleanly

### Claude Desktop config failures
- Config not found: print JSON snippet for manual addition; don't fail the install
- `piighost` key already exists: skip with message; `--force` to overwrite
- Config is malformed JSON: back up original, warn user, skip config step

---

## Out of Scope

- Ollama / local LLM (not part of the "full" bundle defined here)
- Uninstall command (follow-on)
- Auto-update (existing `self_update.py` handles this)
- Non-Claude MCP hosts (Cursor, Zed) — Claude Desktop only for now
