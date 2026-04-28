"""piighost.legal — French legal-citation verification and search.

Lazy public API (PEP 562) to keep startup fast — pulling the
PisteClient + httpx + retry logic only when needed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "extract_references",
    "OutboundRedactor",
    "LegalCache",
    "PisteClient",
    "LegalReference",
    "VerificationResult",
    "LegalHit",
    "LegalRefType",
]


def __getattr__(name: str):
    if name == "extract_references":
        from .ref_extractor import extract_references
        return extract_references
    if name == "OutboundRedactor":
        from .redactor import OutboundRedactor
        return OutboundRedactor
    if name == "LegalCache":
        from .cache import LegalCache
        return LegalCache
    if name == "PisteClient":
        from .piste_client import PisteClient
        return PisteClient
    if name in ("LegalReference", "VerificationResult", "LegalHit", "LegalRefType"):
        from . import reference_models
        return getattr(reference_models, name)
    raise AttributeError(f"module 'piighost.legal' has no attribute {name!r}")


if TYPE_CHECKING:
    from .ref_extractor import extract_references  # noqa: F401
    from .redactor import OutboundRedactor  # noqa: F401
    from .cache import LegalCache  # noqa: F401
    from .piste_client import PisteClient  # noqa: F401
    from .reference_models import (  # noqa: F401
        LegalReference, VerificationResult, LegalHit, LegalRefType,
    )
