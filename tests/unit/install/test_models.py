from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from typing import TYPE_CHECKING

from piighost.install.models import (
    warmup_ner,
    warmup_embedder,
    WarmupError,
)

if TYPE_CHECKING:
    from piighost.service.config import ServiceConfig


def _cfg(gliner2_model: str = "fastino/gliner2-multi-v1",
         embedder_backend: str = "local",
         local_model: str = "OrdalieTech/Solon-embeddings-base-0.1") -> "ServiceConfig":
    from piighost.service.config import ServiceConfig
    cfg = ServiceConfig()
    cfg.detector.gliner2_model = gliner2_model
    cfg.embedder.backend = embedder_backend
    cfg.embedder.local_model = local_model
    return cfg


def test_warmup_ner_dry_run_does_not_call_loaders():
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
