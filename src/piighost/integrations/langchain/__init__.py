"""LangChain integration for PIIGhost (document-pipeline components)."""

import importlib.util

if importlib.util.find_spec("langchain") is None:
    raise ImportError(
        "You must install langchain to use piighost.integrations.langchain, "
        "please install piighost[langchain]"
    )

from piighost.integrations.langchain.transformers import (
    PIIGhostDocumentAnonymizer,
    PIIGhostDocumentClassifier,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)
from piighost.presets import PRESET_GDPR, PRESET_LANGUAGE, PRESET_SENSITIVITY

__all__ = [
    "PIIGhostDocumentAnonymizer",
    "PIIGhostDocumentClassifier",
    "PIIGhostQueryAnonymizer",
    "PIIGhostRehydrator",
    "PRESET_GDPR",
    "PRESET_LANGUAGE",
    "PRESET_SENSITIVITY",
]
