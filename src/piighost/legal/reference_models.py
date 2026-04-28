"""Pydantic shapes for the legal subsystem.

LegalReference     — output of extract_references()
VerificationResult — output of verify_legal_ref()
LegalHit           — output of search_legal()
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LegalRefType(StrEnum):
    ARTICLE_CODE = "ARTICLE_CODE"
    LOI = "LOI"
    DECRET = "DECRET"
    ORDONNANCE = "ORDONNANCE"
    JURISPRUDENCE = "JURISPRUDENCE"
    JOURNAL_OFFICIEL = "JOURNAL_OFFICIEL"
    AUTRE = "AUTRE"


class LegalReference(BaseModel):
    """One legal reference extracted from input text."""
    model_config = ConfigDict(extra="forbid")

    ref_id: int
    ref_type: LegalRefType
    raw_text: str
    numero: Optional[str] = None       # article or law number
    code: Optional[str] = None         # code name (Code civil, …)
    text_id: Optional[str] = None      # AAAA-NNN format for laws/decrees
    date: Optional[str] = None
    juridiction: Optional[str] = None
    formation: Optional[str] = None
    pourvoi: Optional[str] = None
    contenu_cite: Optional[str] = None
    position: int = 0


VerificationStatus = Literal[
    "VERIFIE_EXACT",
    "VERIFIE_MINEUR",
    "PARTIELLEMENT_EXACT",
    "SUBSTANTIELLEMENT_ERRONE",
    "HALLUCINATION",
    "UNKNOWN_OPENLEGI_DISABLED",
    "UNKNOWN_AUTH_FAILED",
    "UNKNOWN_RATE_LIMITED",
    "UNKNOWN_NETWORK",
    "UNKNOWN_PARSE_ERROR",
]


class VerificationResult(BaseModel):
    """Outcome of verifying a single LegalReference against OpenLégi."""
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    score: Optional[int] = None          # 0-100 per the user's taxonomy
    type_erreur: Optional[str] = None    # REF_INEXISTANTE / NUM_ERRONE / …
    url_legifrance: Optional[str] = None
    correction: Optional[str] = None
    message: Optional[str] = None        # human-readable diagnosis


class LegalHit(BaseModel):
    """One result from search_legal()."""
    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "code", "jurisprudence_judiciaire", "jurisprudence_administrative",
        "cnil", "jorf", "lois_decrets", "conventions_collectives",
    ]
    title: str
    snippet: str = ""
    url: Optional[str] = None
    score: Optional[float] = None
