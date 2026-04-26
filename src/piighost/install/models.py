from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from piighost.service.config import ServiceConfig

FRENCH_QUANTIZED_REPO = "jamon8888/french-pii-legal-ner-quantized"
FRENCH_BASE_MODEL = "fastino/gliner2-large-v1"
FRENCH_WEIGHTS_FILE = "adapter_weights_int8.pt"


class WarmupError(RuntimeError):
    pass


def warmup_ner(config: "ServiceConfig", *, dry_run: bool) -> None:
    """Pre-download the base GLiNER2 model and (if configured) its
    LoRA adapter. After this returns, the daemon's first detection
    call finds everything cached on disk and skips the multi-minute
    download — the ~22s MCP initialize timeout never fires.
    """
    if dry_run:
        return
    model_name = config.detector.gliner2_model
    try:
        if model_name == FRENCH_QUANTIZED_REPO:
            _load_french_ner()
        else:
            _load_standard_ner(model_name)

        adapter = getattr(config.detector, "gliner2_adapter", None)
        if adapter:
            _snapshot_adapter(adapter)
    except (ImportError, RuntimeError, OSError) as exc:
        raise WarmupError(f"NER warm-up failed: {exc}") from exc


def _snapshot_adapter(repo_or_path: str) -> None:
    """Download an HF adapter snapshot if ``repo_or_path`` is a repo id.
    Local paths are no-ops (already on disk)."""
    from pathlib import Path
    if Path(repo_or_path).exists():
        return
    from huggingface_hub import snapshot_download
    snapshot_download(repo_or_path)


def warmup_embedder(config: "ServiceConfig", *, dry_run: bool) -> None:
    if dry_run or config.embedder.backend != "local":
        return
    try:
        _load_solon(config.embedder.local_model)
    except (ImportError, RuntimeError, OSError) as exc:
        raise WarmupError(f"Embedder warm-up failed: {exc}") from exc


def warmup_reranker(config: "ServiceConfig", *, dry_run: bool) -> None:
    if dry_run or config.reranker.backend == "none":
        return
    try:
        _load_cross_encoder(config.reranker.cross_encoder_model)
    except (ImportError, RuntimeError, OSError) as exc:
        raise WarmupError(f"Reranker warm-up failed: {exc}") from exc


def warmup(config: "ServiceConfig", *, dry_run: bool) -> None:
    """Pre-download every model the daemon will load on startup so the
    first MCP tool call doesn't hit a multi-minute cold download.

    Called from the install executor when ``plan.warmup_models`` is
    true (default-on). Each of the three sub-warmups respects its own
    backend gate, so e.g. ``embedder.backend = "none"`` is a no-op."""
    warmup_ner(config, dry_run=dry_run)
    warmup_embedder(config, dry_run=dry_run)
    warmup_reranker(config, dry_run=dry_run)


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
