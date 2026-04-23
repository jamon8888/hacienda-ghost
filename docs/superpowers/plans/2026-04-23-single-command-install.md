# Single-Command Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `piighost install --full` command and two bootstrap scripts (`install.sh` / `install.ps1`) that, from a single copy-paste, install piighost with all models and register the MCP server in Claude Desktop.

**Architecture:** A new `src/piighost/install/` module contains one focused file per concern (preflight, ui, claude_config, models, uv_path, docker). `install/__init__.py` is the Typer command that orchestrates them in order. Two shell bootstrap scripts live in `scripts/` and simply ensure `uv` is present before handing off to the Python command.

**Tech Stack:** Python 3.12+, Typer, rich, uv, huggingface_hub, gliner2, sentence-transformers, torch, pytest, pytest-asyncio

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/piighost/install/__init__.py` | Typer `install` command; step orchestrator |
| Create | `src/piighost/install/preflight.py` | Disk, internet, Python version checks |
| Create | `src/piighost/install/ui.py` | `rich` Console + step printer + progress helpers |
| Create | `src/piighost/install/claude_config.py` | Locate, backup, merge `claude_desktop_config.json` |
| Create | `src/piighost/install/models.py` | GLiNER2 + LoRA adapter + Solon warm-up |
| Create | `src/piighost/install/uv_path.py` | `uv tool install` subprocess |
| Create | `src/piighost/install/docker.py` | Docker detection, compose pull/up, healthcheck poll |
| Create | `scripts/install.sh` | Bootstrap for macOS/Linux (`curl \| sh`) |
| Create | `scripts/install.ps1` | Bootstrap for Windows (`irm \| iex`) |
| Create | `tests/unit/install/test_preflight.py` | Unit tests for preflight |
| Create | `tests/unit/install/test_claude_config.py` | Unit tests for config merge |
| Create | `tests/unit/install/test_uv_path.py` | Unit tests for uv detection |
| Create | `tests/unit/install/test_docker.py` | Unit tests for Docker detection |
| Create | `tests/unit/install/test_models.py` | Unit tests for model loader dispatch |
| Create | `tests/unit/install/test_install_cmd.py` | Integration test for `--dry-run` flag |
| Modify | `src/piighost/cli/main.py` | Register `install` subcommand |

---

## Task 1: `install/preflight.py` — pre-flight checks

**Files:**
- Create: `src/piighost/install/preflight.py`
- Create: `tests/unit/install/__init__.py`
- Create: `tests/unit/install/test_preflight.py`

- [ ] **Step 1.1: Write the failing tests**

```python
# tests/unit/install/test_preflight.py
from __future__ import annotations
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from piighost.install.preflight import (
    PreflightError,
    check_disk_space,
    check_internet,
    check_python_version,
)


def test_check_disk_space_passes_when_enough(tmp_path):
    with patch("shutil.disk_usage") as mock_du:
        mock_du.return_value = shutil.disk_usage.__class__(
            total=10 * 1024**3, used=1 * 1024**3, free=9 * 1024**3
        )
        check_disk_space(min_gb=2.0)  # should not raise


def test_check_disk_space_raises_when_insufficient():
    with patch("shutil.disk_usage") as mock_du:
        mock_du.return_value = MagicMock(free=500 * 1024**2)  # 500 MB
        with pytest.raises(PreflightError, match="disk space"):
            check_disk_space(min_gb=2.0)


def test_check_internet_passes_when_reachable():
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        check_internet()  # should not raise


def test_check_internet_raises_when_unreachable():
    with patch("urllib.request.urlopen", side_effect=OSError("no network")):
        with pytest.raises(PreflightError, match="internet"):
            check_internet()


def test_check_python_version_passes():
    with patch("sys.version_info", (3, 12, 0)):
        check_python_version()  # should not raise


def test_check_python_version_raises_for_old_python():
    with patch("sys.version_info", (3, 9, 0)):
        with pytest.raises(PreflightError, match="Python 3.10"):
            check_python_version()
```

- [ ] **Step 1.2: Run tests to verify they fail**

```
uv run pytest tests/unit/install/test_preflight.py -v
```
Expected: `ModuleNotFoundError: No module named 'piighost.install'`

- [ ] **Step 1.3: Create `tests/unit/install/__init__.py`**

```python
# tests/unit/install/__init__.py
```

- [ ] **Step 1.4: Implement `preflight.py`**

```python
# src/piighost/install/preflight.py
from __future__ import annotations

import shutil
import sys
import urllib.request


class PreflightError(RuntimeError):
    pass


def check_disk_space(min_gb: float = 2.0) -> None:
    usage = shutil.disk_usage("/")
    free_gb = usage.free / 1024**3
    if free_gb < min_gb:
        raise PreflightError(
            f"Insufficient disk space: {free_gb:.1f} GB free, {min_gb:.1f} GB required. "
            f"Pass --force to proceed anyway."
        )


def check_internet() -> None:
    try:
        with urllib.request.urlopen("https://pypi.org", timeout=5):
            pass
    except OSError as exc:
        raise PreflightError(
            f"No internet access: {exc}. "
            f"Check your connection or set HTTPS_PROXY."
        ) from exc


def check_python_version() -> None:
    if sys.version_info < (3, 10):
        raise PreflightError(
            f"Python 3.10+ required (found {sys.version_info.major}.{sys.version_info.minor}). "
            f"Run: uv python install 3.12"
        )
```

- [ ] **Step 1.5: Also create the package `__init__.py` placeholder**

```python
# src/piighost/install/__init__.py
# populated in Task 7
```

- [ ] **Step 1.6: Run tests to verify they pass**

```
uv run pytest tests/unit/install/test_preflight.py -v
```
Expected: all 6 tests PASS

- [ ] **Step 1.7: Commit**

```bash
git add src/piighost/install/ tests/unit/install/
git commit -m "feat(install): add preflight checks module"
```

---

## Task 2: `install/ui.py` — rich terminal helpers

**Files:**
- Create: `src/piighost/install/ui.py`

No dedicated tests — this is a thin wrapper over `rich` with no logic. Verified by integration in Task 7.

- [ ] **Step 2.1: Implement `ui.py`**

```python
# src/piighost/install/ui.py
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console()


def step(message: str) -> None:
    console.print(f"\n[bold cyan]→[/bold cyan] {message}")


def success(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {message}")


def warn(message: str) -> None:
    console.print(f"[bold yellow]⚠[/bold yellow] {message}", style="yellow")


def error(message: str) -> None:
    console.print(f"[bold red]✗[/bold red] {message}", style="red")


def info(message: str) -> None:
    console.print(f"  {message}", style="dim")


@contextmanager
def spinner(label: str) -> Generator[None, None, None]:
    with console.status(f"[cyan]{label}[/cyan]"):
        yield


def download_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    )
```

- [ ] **Step 2.2: Commit**

```bash
git add src/piighost/install/ui.py
git commit -m "feat(install): add rich terminal UI helpers"
```

---

## Task 3: `install/claude_config.py` — Claude Desktop config

**Files:**
- Create: `src/piighost/install/claude_config.py`
- Create: `tests/unit/install/test_claude_config.py`

- [ ] **Step 3.1: Write the failing tests**

```python
# tests/unit/install/test_claude_config.py
from __future__ import annotations
import json
from pathlib import Path
import pytest

from piighost.install.claude_config import (
    backup_config,
    find_claude_config,
    merge_mcp_entry,
    AlreadyRegisteredError,
)

MCP_ENTRY = {
    "type": "stdio",
    "command": "uvx",
    "args": ["--from", "piighost[mcp,index,gliner2]", "piighost", "serve", "--transport", "stdio"],
    "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
}


def test_find_claude_config_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    result = find_claude_config()
    assert result is None


def test_backup_config_creates_bak(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text('{"mcpServers": {}}', encoding="utf-8")
    bak = backup_config(cfg)
    assert bak.exists()
    assert bak.suffix == ".bak"
    assert bak.read_text() == cfg.read_text()


def test_merge_mcp_entry_adds_new_key(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text('{"mcpServers": {}}', encoding="utf-8")
    merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=False)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piighost"] == MCP_ENTRY


def test_merge_mcp_entry_raises_if_already_registered(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"piighost": {"type": "stdio"}}}), encoding="utf-8"
    )
    with pytest.raises(AlreadyRegisteredError):
        merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=False)


def test_merge_mcp_entry_overwrites_with_force(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"piighost": {"type": "old"}}}), encoding="utf-8"
    )
    merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=True)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piighost"] == MCP_ENTRY


def test_merge_mcp_entry_preserves_other_servers(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"other": {"type": "stdio"}}}), encoding="utf-8"
    )
    merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=False)
    data = json.loads(cfg.read_text())
    assert "other" in data["mcpServers"]
    assert "piighost" in data["mcpServers"]


def test_merge_mcp_entry_handles_missing_mcp_servers_key(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text("{}", encoding="utf-8")
    merge_mcp_entry(cfg, "piighost", MCP_ENTRY, force=False)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piighost"] == MCP_ENTRY
```

- [ ] **Step 3.2: Run tests to verify they fail**

```
uv run pytest tests/unit/install/test_claude_config.py -v
```
Expected: `ImportError: cannot import name 'merge_mcp_entry'`

- [ ] **Step 3.3: Implement `claude_config.py`**

```python
# src/piighost/install/claude_config.py
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


class AlreadyRegisteredError(RuntimeError):
    pass


class MalformedConfigError(RuntimeError):
    pass


def find_claude_config() -> Path | None:
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        p = Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:
        p = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    return p if p.exists() else None


def backup_config(path: Path) -> Path:
    bak = path.with_suffix(".json.bak")
    shutil.copy2(path, bak)
    return bak


def merge_mcp_entry(
    path: Path, key: str, entry: dict, *, force: bool
) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MalformedConfigError(
            f"Cannot parse {path}: {exc}. Skipping config registration."
        ) from exc

    servers: dict = data.setdefault("mcpServers", {})
    if key in servers and not force:
        raise AlreadyRegisteredError(
            f"'{key}' already registered in {path}. Use --force to overwrite."
        )
    servers[key] = entry
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

- [ ] **Step 3.4: Run tests to verify they pass**

```
uv run pytest tests/unit/install/test_claude_config.py -v
```
Expected: all 7 tests PASS

- [ ] **Step 3.5: Commit**

```bash
git add src/piighost/install/claude_config.py tests/unit/install/test_claude_config.py
git commit -m "feat(install): add Claude Desktop config merge module"
```

---

## Task 4: `install/models.py` — model warm-up

**Files:**
- Create: `src/piighost/install/models.py`
- Create: `tests/unit/install/test_models.py`

- [ ] **Step 4.1: Write the failing tests**

```python
# tests/unit/install/test_models.py
from __future__ import annotations
from unittest.mock import MagicMock, patch, call
import pytest

from piighost.install.models import (
    warmup_ner,
    warmup_embedder,
    WarmupError,
)
from piighost.service.config import ServiceConfig


def _cfg(gliner2_model: str = "fastino/gliner2-multi-v1",
         embedder_backend: str = "local",
         local_model: str = "OrdalieTech/Solon-embeddings-base-0.1") -> ServiceConfig:
    cfg = ServiceConfig()
    cfg.detector.gliner2_model = gliner2_model
    cfg.embedder.backend = embedder_backend
    cfg.embedder.local_model = local_model
    return cfg


def test_warmup_ner_dry_run_does_not_import(monkeypatch):
    imported = []
    monkeypatch.setattr("builtins.__import__", lambda name, *a, **kw: imported.append(name))
    # dry_run should not call any real import
    with patch("piighost.install.models._load_standard_ner") as mock_std:
        with patch("piighost.install.models._load_french_ner") as mock_fr:
            warmup_ner(_cfg(), dry_run=True)
            mock_std.assert_not_called()
            mock_fr.assert_not_called()


def test_warmup_ner_calls_french_loader_for_quantized_model():
    cfg = _cfg(gliner2_model="jamon8888/french-pii-legal-ner-quantized")
    with patch("piighost.install.models._load_french_ner") as mock_fr:
        warmup_ner(cfg, dry_run=False)
        mock_fr.assert_called_once()


def test_warmup_ner_calls_standard_loader_for_other_models():
    cfg = _cfg(gliner2_model="fastino/gliner2-multi-v1")
    with patch("piighost.install.models._load_standard_ner") as mock_std:
        warmup_ner(cfg, dry_run=False)
        mock_std.assert_called_once_with("fastino/gliner2-multi-v1")


def test_warmup_embedder_dry_run_skips():
    with patch("piighost.install.models._load_solon") as mock_solon:
        warmup_embedder(_cfg(), dry_run=True)
        mock_solon.assert_not_called()


def test_warmup_embedder_calls_solon_for_local_backend():
    cfg = _cfg(embedder_backend="local", local_model="OrdalieTech/Solon-embeddings-base-0.1")
    with patch("piighost.install.models._load_solon") as mock_solon:
        warmup_embedder(cfg, dry_run=False)
        mock_solon.assert_called_once_with("OrdalieTech/Solon-embeddings-base-0.1")


def test_warmup_embedder_skips_for_non_local_backend():
    cfg = _cfg(embedder_backend="mistral")
    with patch("piighost.install.models._load_solon") as mock_solon:
        warmup_embedder(cfg, dry_run=False)
        mock_solon.assert_not_called()


def test_warmup_ner_wraps_import_error():
    cfg = _cfg(gliner2_model="fastino/gliner2-multi-v1")
    with patch("piighost.install.models._load_standard_ner", side_effect=ImportError("gliner2 not found")):
        with pytest.raises(WarmupError, match="gliner2 not found"):
            warmup_ner(cfg, dry_run=False)
```

- [ ] **Step 4.2: Run tests to verify they fail**

```
uv run pytest tests/unit/install/test_models.py -v
```
Expected: `ImportError: cannot import name 'warmup_ner'`

- [ ] **Step 4.3: Implement `models.py`**

```python
# src/piighost/install/models.py
from __future__ import annotations

from piighost.service.config import ServiceConfig

FRENCH_QUANTIZED_REPO = "jamon8888/french-pii-legal-ner-quantized"
FRENCH_BASE_MODEL = "fastino/gliner2-large-v1"
FRENCH_WEIGHTS_FILE = "adapter_weights_int8.pt"


class WarmupError(RuntimeError):
    pass


def warmup_ner(config: ServiceConfig, *, dry_run: bool) -> None:
    if dry_run:
        return
    model_name = config.detector.gliner2_model
    try:
        if model_name == FRENCH_QUANTIZED_REPO:
            _load_french_ner()
        else:
            _load_standard_ner(model_name)
    except (ImportError, RuntimeError, OSError) as exc:
        raise WarmupError(f"NER warm-up failed: {exc}") from exc


def warmup_embedder(config: ServiceConfig, *, dry_run: bool) -> None:
    if dry_run or config.embedder.backend != "local":
        return
    try:
        _load_solon(config.embedder.local_model)
    except (ImportError, RuntimeError, OSError) as exc:
        raise WarmupError(f"Embedder warm-up failed: {exc}") from exc


def warmup_reranker(config: ServiceConfig, *, dry_run: bool) -> None:
    if dry_run or config.reranker.backend == "none":
        return
    try:
        _load_cross_encoder(config.reranker.cross_encoder_model)
    except (ImportError, RuntimeError, OSError) as exc:
        raise WarmupError(f"Reranker warm-up failed: {exc}") from exc


def _load_standard_ner(model_name: str) -> None:
    from gliner2 import GLiNER2
    GLiNER2.from_pretrained(model_name)


def _load_french_ner() -> None:
    import torch
    from gliner2 import GLiNER2
    from gliner2.training.lora import LoRAConfig, apply_lora_to_model
    from huggingface_hub import hf_hub_download

    model = GLiNER2.from_pretrained(FRENCH_BASE_MODEL)
    lora_cfg = LoRAConfig(enabled=True, r=16, alpha=32.0, dropout=0.0, target_modules=["encoder"])
    model, _ = apply_lora_to_model(model, lora_cfg)
    torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)
    weights_path = hf_hub_download(FRENCH_QUANTIZED_REPO, FRENCH_WEIGHTS_FILE)
    state_dict = torch.load(weights_path, map_location="cpu", weights_only=False)
    model.load_state_dict(state_dict)
    model.train(False)


def _load_solon(model_name: str) -> None:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer(model_name)


def _load_cross_encoder(model_name: str) -> None:
    from sentence_transformers import CrossEncoder
    CrossEncoder(model_name)
```

- [ ] **Step 4.4: Run tests to verify they pass**

```
uv run pytest tests/unit/install/test_models.py -v
```
Expected: all 7 tests PASS

- [ ] **Step 4.5: Commit**

```bash
git add src/piighost/install/models.py tests/unit/install/test_models.py
git commit -m "feat(install): add model warm-up module (GLiNER2 + Solon)"
```

---

## Task 5: `install/uv_path.py` — uv installation path

**Files:**
- Create: `src/piighost/install/uv_path.py`
- Create: `tests/unit/install/test_uv_path.py`

- [ ] **Step 5.1: Write the failing tests**

```python
# tests/unit/install/test_uv_path.py
from __future__ import annotations
import subprocess
from unittest.mock import patch, MagicMock
import pytest

from piighost.install.uv_path import ensure_uv, install_piighost, UvNotFoundError


def test_ensure_uv_returns_path_when_found():
    with patch("shutil.which", return_value="/usr/local/bin/uv"):
        path = ensure_uv()
        assert path == "/usr/local/bin/uv"


def test_ensure_uv_raises_when_missing():
    with patch("shutil.which", return_value=None):
        with pytest.raises(UvNotFoundError):
            ensure_uv()


def test_install_piighost_dry_run_returns_without_subprocess():
    with patch("subprocess.run") as mock_run:
        install_piighost(uv_path="uv", dry_run=True)
        mock_run.assert_not_called()


def test_install_piighost_calls_uv_tool_install():
    with patch("shutil.which", return_value="uv"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            install_piighost(uv_path="uv", dry_run=False)
            args = mock_run.call_args[0][0]
            assert "uv" in args
            assert "tool" in args
            assert "install" in args
            assert any("piighost" in a for a in args)


def test_install_piighost_raises_on_subprocess_failure():
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "uv")):
        with pytest.raises(RuntimeError, match="uv tool install failed"):
            install_piighost(uv_path="uv", dry_run=False)
```

- [ ] **Step 5.2: Run tests to verify they fail**

```
uv run pytest tests/unit/install/test_uv_path.py -v
```
Expected: `ImportError: cannot import name 'ensure_uv'`

- [ ] **Step 5.3: Implement `uv_path.py`**

```python
# src/piighost/install/uv_path.py
from __future__ import annotations

import shutil
import subprocess
import sys


class UvNotFoundError(RuntimeError):
    pass


def ensure_uv() -> str:
    path = shutil.which("uv")
    if path is None:
        raise UvNotFoundError(
            "uv not found on PATH. Install from https://astral.sh/uv "
            "or run: pip install uv"
        )
    return path


def install_piighost(*, uv_path: str, dry_run: bool) -> None:
    if dry_run:
        return
    cmd = [
        uv_path, "tool", "install",
        "piighost[mcp,index,gliner2]",
        "--python", "3.12",
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"uv tool install failed (exit {exc.returncode}). "
            f"Fallback: pip install \"piighost[mcp,index,gliner2]\""
        ) from exc
```

- [ ] **Step 5.4: Run tests to verify they pass**

```
uv run pytest tests/unit/install/test_uv_path.py -v
```
Expected: all 5 tests PASS

- [ ] **Step 5.5: Commit**

```bash
git add src/piighost/install/uv_path.py tests/unit/install/test_uv_path.py
git commit -m "feat(install): add uv installation path module"
```

---

## Task 6: `install/docker.py` — Docker detection and compose management

**Files:**
- Create: `src/piighost/install/docker.py`
- Create: `tests/unit/install/test_docker.py`

- [ ] **Step 6.1: Write the failing tests**

```python
# tests/unit/install/test_docker.py
from __future__ import annotations
import subprocess
import time
from unittest.mock import patch, MagicMock
import pytest

from piighost.install.docker import docker_available, compose_pull_and_up, DockerError


def test_docker_available_returns_true_when_daemon_running():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert docker_available() is True


def test_docker_available_returns_false_when_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        assert docker_available() is False


def test_docker_available_returns_false_when_daemon_not_running():
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")):
        assert docker_available() is False


def test_compose_pull_and_up_dry_run_skips_subprocess():
    with patch("subprocess.run") as mock_run:
        compose_pull_and_up(dry_run=True)
        mock_run.assert_not_called()


def test_compose_pull_and_up_calls_pull_then_up():
    calls = []
    def capture(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)
    with patch("subprocess.run", side_effect=capture):
        with patch("piighost.install.docker._wait_for_healthy", return_value=True):
            compose_pull_and_up(dry_run=False)
    assert any("pull" in c for c in calls)
    assert any("up" in c for c in calls)


def test_compose_pull_and_up_raises_on_pull_failure():
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")):
        with pytest.raises(DockerError, match="compose pull failed"):
            compose_pull_and_up(dry_run=False)
```

- [ ] **Step 6.2: Run tests to verify they fail**

```
uv run pytest tests/unit/install/test_docker.py -v
```
Expected: `ImportError: cannot import name 'docker_available'`

- [ ] **Step 6.3: Implement `docker.py`**

```python
# src/piighost/install/docker.py
from __future__ import annotations

import subprocess
import time


class DockerError(RuntimeError):
    pass


def docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def compose_pull_and_up(*, dry_run: bool) -> None:
    if dry_run:
        return
    _compose_pull()
    _compose_up()
    if not _wait_for_healthy(timeout_s=180):
        raise DockerError("Services did not become healthy within 3 minutes.")


def _compose_pull() -> None:
    cmd = [
        "docker", "compose",
        "-f", "docker-compose.yml",
        "-f", "docker-compose.embedder.yml",
        "pull",
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise DockerError(
            f"docker compose pull failed (exit {exc.returncode}). "
            f"Use --no-docker to skip Docker and install via uv instead."
        ) from exc


def _compose_up() -> None:
    cmd = [
        "docker", "compose",
        "-f", "docker-compose.yml",
        "-f", "docker-compose.embedder.yml",
        "up", "-d",
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise DockerError(f"docker compose up failed (exit {exc.returncode}).") from exc


def _wait_for_healthy(timeout_s: int = 180, poll_s: int = 5) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "{{.Health}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            statuses = [s.strip() for s in result.stdout.splitlines() if s.strip()]
            if statuses and all(s == "healthy" for s in statuses):
                return True
        except subprocess.CalledProcessError:
            pass
        time.sleep(poll_s)
    return False
```

- [ ] **Step 6.4: Run tests to verify they pass**

```
uv run pytest tests/unit/install/test_docker.py -v
```
Expected: all 6 tests PASS

- [ ] **Step 6.5: Commit**

```bash
git add src/piighost/install/docker.py tests/unit/install/test_docker.py
git commit -m "feat(install): add Docker detection and compose management module"
```

---

## Task 7: `install/__init__.py` — Typer command orchestrator

**Files:**
- Modify: `src/piighost/install/__init__.py`
- Create: `tests/unit/install/test_install_cmd.py`

- [ ] **Step 7.1: Write the failing tests**

```python
# tests/unit/install/test_install_cmd.py
from __future__ import annotations
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
import pytest

from piighost.cli.main import app

runner = CliRunner()


def _all_mocked():
    """Context manager patches for all install sub-steps."""
    return [
        patch("piighost.install.preflight.check_disk_space"),
        patch("piighost.install.preflight.check_internet"),
        patch("piighost.install.preflight.check_python_version"),
        patch("piighost.install.docker.docker_available", return_value=False),
        patch("piighost.install.uv_path.ensure_uv", return_value="uv"),
        patch("piighost.install.uv_path.install_piighost"),
        patch("piighost.install.models.warmup_ner"),
        patch("piighost.install.models.warmup_embedder"),
        patch("piighost.install.claude_config.find_claude_config", return_value=None),
    ]


def test_install_dry_run_exits_zero():
    from contextlib import ExitStack
    with ExitStack() as stack:
        for m in _all_mocked():
            stack.enter_context(m)
        result = runner.invoke(app, ["install", "--full", "--dry-run"])
    assert result.exit_code == 0


def test_install_no_docker_forces_uv_path():
    from contextlib import ExitStack
    with ExitStack() as stack:
        for m in _all_mocked():
            stack.enter_context(m)
        uv_install = stack.enter_context(patch("piighost.install.uv_path.install_piighost"))
        result = runner.invoke(app, ["install", "--full", "--no-docker", "--dry-run"])
    assert result.exit_code == 0


def test_install_fails_gracefully_on_preflight_error():
    from piighost.install.preflight import PreflightError
    with patch("piighost.install.preflight.check_disk_space", side_effect=PreflightError("no space")):
        result = runner.invoke(app, ["install", "--full"])
    assert result.exit_code != 0
    assert "no space" in result.output
```

- [ ] **Step 7.2: Run tests to verify they fail**

```
uv run pytest tests/unit/install/test_install_cmd.py -v
```
Expected: `Error: No such command 'install'` (command not yet registered)

- [ ] **Step 7.3: Implement `install/__init__.py`**

```python
# src/piighost/install/__init__.py
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from piighost.install import claude_config, docker, models, preflight, uv_path
from piighost.install.ui import error, info, step, success, warn
from piighost.service.config import ServiceConfig

MCP_ENTRY_UV = {
    "type": "stdio",
    "command": "uvx",
    "args": [
        "--from", "piighost[mcp,index,gliner2]",
        "piighost", "serve", "--transport", "stdio",
    ],
    "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
}

MCP_ENTRY_DOCKER = {
    "type": "sse",
    "url": "http://localhost:8080/sse",
}


def run(
    full: Annotated[bool, typer.Option("--full", help="Download all models")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print actions without executing")] = False,
    no_docker: Annotated[bool, typer.Option("--no-docker", help="Force uv path")] = False,
    reranker: Annotated[bool, typer.Option("--reranker", help="Also warm up reranker")] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing config; ignore disk warning")] = False,
) -> None:
    """Install piighost with all models and register it in Claude Desktop."""
    if dry_run:
        info("Dry run — no changes will be made.")

    # Step 1: Pre-flight
    step("Pre-flight checks")
    try:
        preflight.check_python_version()
        try:
            preflight.check_disk_space(min_gb=2.0)
        except preflight.PreflightError as exc:
            if not force:
                error(str(exc))
                raise typer.Exit(code=1)
            warn(f"{exc} — continuing because --force was passed.")
        preflight.check_internet()
    except preflight.PreflightError as exc:
        error(str(exc))
        raise typer.Exit(code=1)
    success("Pre-flight checks passed.")

    # Step 2: Docker detection
    use_docker = False
    if not no_docker:
        step("Detecting Docker")
        use_docker = docker.docker_available()
        if use_docker:
            info("Docker daemon is running — using Docker path.")
        else:
            info("Docker not available — using uv path.")

    # Step 3: Install backend
    if use_docker:
        step("Pulling and starting Docker services")
        try:
            docker.compose_pull_and_up(dry_run=dry_run)
        except docker.DockerError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        success("Docker services running.")
    else:
        step("Installing piighost via uv")
        try:
            uv_bin = uv_path.ensure_uv()
        except uv_path.UvNotFoundError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        try:
            uv_path.install_piighost(uv_path=uv_bin, dry_run=dry_run)
        except RuntimeError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        success("piighost installed.")

    # Step 4: Model warm-up
    if full:
        cfg = _load_config()
        step("Warming up NER model (GLiNER2 + French adapter)")
        try:
            models.warmup_ner(cfg, dry_run=dry_run)
        except models.WarmupError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        success("NER model ready.")

        step("Warming up embedder model (Solon)")
        try:
            models.warmup_embedder(cfg, dry_run=dry_run)
        except models.WarmupError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        success("Embedder model ready.")

        if reranker:
            step("Warming up reranker model (BGE)")
            try:
                models.warmup_reranker(cfg, dry_run=dry_run)
            except models.WarmupError as exc:
                error(str(exc))
                raise typer.Exit(code=1)
            success("Reranker model ready.")

    # Step 5: Claude Desktop config
    step("Registering MCP server in Claude Desktop")
    mcp_entry = MCP_ENTRY_DOCKER if use_docker else MCP_ENTRY_UV
    config_path = claude_config.find_claude_config()
    if config_path is None:
        warn("Claude Desktop config not found. Add this to claude_desktop_config.json manually:")
        import json
        info(json.dumps({"mcpServers": {"piighost": mcp_entry}}, indent=2))
    else:
        try:
            claude_config.backup_config(config_path)
            claude_config.merge_mcp_entry(config_path, "piighost", mcp_entry, force=force)
            success(f"Registered in {config_path}")
        except claude_config.AlreadyRegisteredError as exc:
            warn(str(exc))
        except claude_config.MalformedConfigError as exc:
            warn(str(exc))

    # Done
    success("\npiighost is ready. Restart Claude Desktop to activate the MCP server.")


def _load_config() -> ServiceConfig:
    config_path = Path(".piighost") / "config.toml"
    if config_path.exists():
        return ServiceConfig.from_toml(config_path)
    return ServiceConfig.default()
```

- [ ] **Step 7.4: Run tests to verify they pass**

```
uv run pytest tests/unit/install/test_install_cmd.py -v
```
Expected: still fails — `install` not yet registered in `cli/main.py`. Move to Task 8.

---

## Task 8: Wire `piighost install` into `cli/main.py`

**Files:**
- Modify: `src/piighost/cli/main.py`

- [ ] **Step 8.1: Add the install command registration**

Open `src/piighost/cli/main.py` and add two lines — one import and one registration:

```python
# src/piighost/cli/main.py
from __future__ import annotations

import typer

from piighost.cli.commands import anonymize as anonymize_cmd
from piighost.cli.commands import detect as detect_cmd
from piighost.cli.commands import index as index_cmd
from piighost.cli.commands import index_status as index_status_cmd
from piighost.cli.commands import init as init_cmd
from piighost.cli.commands import query as query_cmd
from piighost.cli.commands import rehydrate as rehydrate_cmd
from piighost.cli.commands import rm as rm_cmd
from piighost.cli.commands import serve as serve_cmd
from piighost.cli.commands.daemon import daemon_app
from piighost.cli.commands.projects import app as projects_app
from piighost.cli.commands.vault import vault_app
from piighost.cli.docker_cmd import app as docker_app
from piighost.cli.self_update import app as self_update_app
from piighost.install import run as install_run        # <-- add this

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="piighost — GDPR-compliant PII anonymization CLI",
)

app.command("init")(init_cmd.run)
app.command("anonymize")(anonymize_cmd.run)
app.command("rehydrate")(rehydrate_cmd.run)
app.command("detect")(detect_cmd.run)
app.command("index")(index_cmd.run)
app.command("query")(query_cmd.run)
app.command("serve")(serve_cmd.run)
app.command("rm")(rm_cmd.run)
app.command("index-status")(index_status_cmd.run)
app.command("install")(install_run)                    # <-- add this
app.add_typer(vault_app, name="vault")
app.add_typer(daemon_app, name="daemon")
app.add_typer(projects_app, name="projects")
app.add_typer(docker_app, name="docker")
app.add_typer(self_update_app, name="self-update")
```

- [ ] **Step 8.2: Run the install command tests**

```
uv run pytest tests/unit/install/ -v
```
Expected: all tests PASS

- [ ] **Step 8.3: Smoke test the help output**

```
uv run python -m piighost.cli.main install --help
```
Expected output includes: `--full`, `--dry-run`, `--no-docker`, `--reranker`, `--force`

- [ ] **Step 8.4: Commit**

```bash
git add src/piighost/cli/main.py src/piighost/install/__init__.py
git commit -m "feat(install): wire piighost install command into CLI"
```

---

## Task 9: Bootstrap scripts

**Files:**
- Create: `scripts/install.sh`
- Create: `scripts/install.ps1`

No automated tests — these are thin shell wrappers verified by manual smoke test on each platform.

- [ ] **Step 9.1: Create `scripts/install.sh`**

```bash
#!/usr/bin/env sh
# install.sh — piighost one-command installer for macOS / Linux
# Usage: curl -LsSf https://piighost.dev/install.sh | sh
set -eu

PIIGHOST_EXTRAS="mcp,index,gliner2"

# 1. Ensure uv is present
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add uv to PATH for the remainder of this script
    export PATH="$HOME/.local/bin:$PATH"
fi

# 2. Install piighost (quiet, so uv's own output is the only noise)
echo "Installing piighost[${PIIGHOST_EXTRAS}]..."
uv tool install "piighost[${PIIGHOST_EXTRAS}]" --python 3.12

# 3. Run the Python installer to warm up models and register Claude Desktop
echo "Running piighost install --full ..."
piighost install --full
```

- [ ] **Step 9.2: Make it executable**

```bash
chmod +x scripts/install.sh
```

- [ ] **Step 9.3: Create `scripts/install.ps1`**

```powershell
# install.ps1 — piighost one-command installer for Windows
# Usage: irm https://piighost.dev/install.ps1 | iex
$ErrorActionPreference = 'Stop'

$EXTRAS = "mcp,index,gliner2"

# 1. Ensure uv is present
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    # Refresh PATH so uv is visible
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
}

# 2. Install piighost
Write-Host "Installing piighost[$EXTRAS]..."
uv tool install "piighost[$EXTRAS]" --python 3.12

# 3. Run the Python installer
Write-Host "Running piighost install --full ..."
piighost install --full
```

- [ ] **Step 9.4: Commit**

```bash
git add scripts/install.sh scripts/install.ps1
git commit -m "feat(install): add curl/irm one-command bootstrap scripts"
```

---

## Task 10: Run full test suite and verify no regressions

- [ ] **Step 10.1: Run all unit tests**

```
uv run pytest tests/unit/ -v --tb=short
```
Expected: all existing tests PASS + new install tests PASS

- [ ] **Step 10.2: Run the dry-run end-to-end**

```
uv run piighost install --full --dry-run
```
Expected output:
```
→ Pre-flight checks
✓ Pre-flight checks passed.
→ Detecting Docker
  Docker not available — using uv path.
→ Installing piighost via uv
  Dry run — no changes will be made.
  ...
✓ piighost is ready. Restart Claude Desktop to activate the MCP server.
```
Exit code: 0

- [ ] **Step 10.3: Verify help output**

```
uv run piighost install --help
```
Expected: all 5 flags shown (`--full`, `--dry-run`, `--no-docker`, `--reranker`, `--force`)

- [ ] **Step 10.4: Commit**

```bash
git add .
git commit -m "test(install): verify full test suite and dry-run smoke test pass"
```

---

## Self-Review

**Spec coverage check:**
- [x] `curl | sh` / `irm | iex` one-liner → Task 9
- [x] Thin bootstrap → Python installer handoff → Tasks 9 + 7
- [x] Docker if available, uv fallback → Tasks 6 + 7
- [x] Interactive progress bar (rich) → Task 2
- [x] GLiNER2 base + French LoRA adapter warm-up → Task 4 (`_load_french_ner`)
- [x] Solon embedder warm-up → Task 4 (`_load_solon`)
- [x] Reranker opt-in → Task 7 (`--reranker` flag)
- [x] Claude Desktop config registration (both paths) → Task 3 + 7
- [x] Pre-flight: disk, internet, Python version → Task 1
- [x] `--dry-run`, `--no-docker`, `--force`, `--reranker` flags → Task 7
- [x] All steps idempotent → uv `tool install` upgrades in place; config merge skips if key exists
- [x] Error handling: all failure modes covered → Tasks 1–7 raise typed exceptions caught in Task 7

**Placeholder scan:** No TBDs. All code blocks are complete.

**Type consistency:**
- `warmup_ner(config: ServiceConfig, *, dry_run: bool)` — used consistently in Task 4 definition and Task 7 call
- `merge_mcp_entry(path, key, entry, *, force)` — consistent between Task 3 definition and Task 7 call
- `compose_pull_and_up(*, dry_run: bool)` — consistent between Task 6 definition and Task 7 call
- `install_piighost(*, uv_path: str, dry_run: bool)` — consistent between Task 5 definition and Task 7 call
