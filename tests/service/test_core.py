from pathlib import Path

import pytest

from piighost.exceptions import PIISafetyViolation
from piighost.service import PIIGhostService, ServiceConfig


class _StubDetector:
    """Deterministic Alice/Paris stub so tests don't need GLiNER2 weights."""

    async def detect(self, text: str) -> list:
        from piighost.models import Detection, Span

        out: list = []
        for needle, label in (("Alice", "PERSON"), ("Paris", "LOC")):
            idx = text.find(needle)
            if idx >= 0:
                out.append(
                    Detection(
                        text=needle,
                        label=label,
                        position=Span(start_pos=idx, end_pos=idx + len(needle)),
                        confidence=0.99,
                    )
                )
        return out


@pytest.fixture()
def vault_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".piighost"
    d.mkdir()
    (d / "config.toml").write_text("schema_version = 1\n", encoding="utf-8")
    return d


@pytest.mark.asyncio
async def test_anonymize_persists_entities(vault_dir: Path) -> None:
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=ServiceConfig.default(),
        detector=_StubDetector(),
    )
    try:
        r = await svc.anonymize("Alice lives in Paris", doc_id="doc1")
        assert "Alice" not in r.anonymized
        assert "Paris" not in r.anonymized
        assert r.anonymized.count("<PERSON:") == 1
        assert r.anonymized.count("<LOC:") == 1
        assert len(r.entities) == 2
        stats = await svc.vault_stats()
        assert stats.total == 2
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_rehydrate_roundtrip(vault_dir: Path) -> None:
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=ServiceConfig.default(),
        detector=_StubDetector(),
    )
    try:
        anon = await svc.anonymize("Alice met Alice in Paris")
        rehydrated = await svc.rehydrate(anon.anonymized)
        assert rehydrated.text == "Alice met Alice in Paris"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_rehydrate_strict_rejects_unknown_token(vault_dir: Path) -> None:
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=ServiceConfig.default(),
        detector=_StubDetector(),
    )
    try:
        with pytest.raises(PIISafetyViolation):
            await svc.rehydrate("Hello <PERSON:deadbeef>!", strict=True)
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_detect_does_not_mutate_vault(vault_dir: Path) -> None:
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=ServiceConfig.default(),
        detector=_StubDetector(),
    )
    try:
        await svc.detect("Alice lives in Paris")
        stats = await svc.vault_stats()
        assert stats.total == 0
    finally:
        await svc.close()
