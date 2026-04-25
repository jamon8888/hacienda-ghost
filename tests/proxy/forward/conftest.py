"""Shared fixtures for forward-proxy tests."""
from __future__ import annotations

from typing import Any

import pytest


class StubAnonymizationService:
    """Drop-in for the anonymization Service protocol used by handlers.

    Replaces every occurrence of the literal string "PATRICK" with
    the placeholder "<<PERSON_1>>" and reverses on rehydrate. Keeps
    tests fully deterministic without loading GLiNER2.
    """

    PII = "PATRICK"
    PLACEHOLDER = "<<PERSON_1>>"

    def __init__(self) -> None:
        self.calls_anonymize: list[str] = []
        self.calls_rehydrate: list[str] = []

    async def anonymize(self, text: str, *, project: str) -> tuple[str, dict[str, Any]]:
        self.calls_anonymize.append(text)
        replaced = text.replace(self.PII, self.PLACEHOLDER)
        meta = {"entities": [{"text": self.PII, "label": "PERSON"}] if self.PII in text else []}
        return replaced, meta

    async def rehydrate(self, text: str, *, project: str) -> str:
        self.calls_rehydrate.append(text)
        return text.replace(self.PLACEHOLDER, self.PII)

    async def active_project(self) -> str:
        return "test-project"


@pytest.fixture
def stub_service() -> StubAnonymizationService:
    return StubAnonymizationService()
