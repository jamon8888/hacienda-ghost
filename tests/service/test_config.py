from pathlib import Path

import pytest

from piighost.service.config import ServiceConfig


def test_from_toml_roundtrip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
schema_version = 1

[vault]
placeholder_factory = "hash"
audit_log = true

[detector]
backend = "gliner2"
gliner2_model = "fastino/gliner2-multi-v1"
threshold = 0.5
labels = ["PERSON", "LOC"]

[daemon]
idle_timeout_sec = 3600
log_level = "info"
max_workers = 4

[safety]
strict_rehydrate = true
max_doc_bytes = 10485760
redact_errors = true
""",
        encoding="utf-8",
    )
    cfg = ServiceConfig.from_toml(cfg_path)
    assert cfg.schema_version == 1
    assert cfg.vault.placeholder_factory == "hash"
    assert cfg.detector.backend == "gliner2"
    assert cfg.detector.labels == ["PERSON", "LOC"]
    assert cfg.safety.strict_rehydrate is True


def test_rejects_counter_placeholder(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
schema_version = 1
[vault]
placeholder_factory = "counter"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash"):
        ServiceConfig.from_toml(cfg_path)


def test_defaults_when_missing_sections(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("schema_version = 1\n", encoding="utf-8")
    cfg = ServiceConfig.from_toml(cfg_path)
    assert cfg.vault.placeholder_factory == "hash"
    assert cfg.detector.backend == "gliner2"
    assert cfg.safety.strict_rehydrate is True
