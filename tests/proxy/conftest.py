from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def stub_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary vault configured to use the stub detector (no GLiNER2)."""
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    d = tmp_path / ".piighost"
    d.mkdir()
    (d / "config.toml").write_text("schema_version = 1\n", encoding="utf-8")
    return d
