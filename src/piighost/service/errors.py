"""Service-layer exceptions. Messages never contain raw PII."""

from __future__ import annotations


class ServiceError(Exception):
    """Base class. Subclasses take structured fields, not PII text."""


class AnonymizationFailed(ServiceError):
    def __init__(self, doc_id: str, stage: str, entity_count: int) -> None:
        super().__init__(
            f"Anonymization failed at stage={stage} for doc={doc_id} "
            f"after detecting {entity_count} entities"
        )
        self.doc_id = doc_id
        self.stage = stage
        self.entity_count = entity_count
