"""Stateful service layer for piighost CLI, daemon, and MCP."""

from piighost.service.config import ServiceConfig
from piighost.service.core import PIIGhostService
from piighost.service.errors import AnonymizationFailed, ServiceError
from piighost.service.models import (
    AnonymizeResult,
    DetectionResult,
    EntityRef,
    RehydrateResult,
    VaultEntryModel,
    VaultPage,
    VaultStatsModel,
)

__all__ = [
    "AnonymizationFailed",
    "AnonymizeResult",
    "DetectionResult",
    "EntityRef",
    "PIIGhostService",
    "RehydrateResult",
    "ServiceConfig",
    "ServiceError",
    "VaultEntryModel",
    "VaultPage",
    "VaultStatsModel",
]
