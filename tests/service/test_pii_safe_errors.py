"""Fuzz test: AnonymizationFailed errors must never leak raw PII.

This is a property-style regression guard. If a future change adds an
f-string or repr of user text into an error message, this test should
fail for at least one of the 100 random inputs.
"""

from __future__ import annotations

import random
import string
from pathlib import Path

import pytest

from piighost.models import Detection, Span
from piighost.service import PIIGhostService, ServiceConfig
from piighost.service.errors import AnonymizationFailed


class _BrokenAnonymizer:
    """Detector that reports a bogus span pointing at text that isn't there.

    The span claims a PERSON entity "SECRETNAME" at offsets [0, 10) which
    will not match the actual input, forcing the anonymization pipeline
    into its failure paths so we can inspect error messages.
    """

    async def detect(self, text: str) -> list[Detection]:
        return [
            Detection(
                text="SECRETNAME",
                label="PERSON",
                position=Span(start_pos=0, end_pos=10),
                confidence=0.99,
            )
        ]


@pytest.mark.asyncio
async def test_fuzz_no_raw_pii_in_error_messages(tmp_path: Path) -> None:
    rng = random.Random(0xB00B)

    vault_dir = tmp_path / ".piighost"
    vault_dir.mkdir()
    (vault_dir / "config.toml").write_text("schema_version = 1\n", encoding="utf-8")

    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=ServiceConfig.default(),
        detector=_BrokenAnonymizer(),
    )
    try:
        for _ in range(100):
            s = "".join(rng.choices(string.ascii_letters, k=12))
            payload = s + " is here"
            try:
                await svc.anonymize(payload)
            except AnonymizationFailed as exc:
                assert s not in str(exc), (
                    "Raw secret leaked into AnonymizationFailed message"
                )
    finally:
        await svc.close()
