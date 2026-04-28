"""Pydantic shapes for the legal subsystem."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from piighost.legal.reference_models import (
    LegalReference,
    VerificationResult,
    LegalHit,
    LegalRefType,
)


def test_legal_reference_minimal_construction():
    r = LegalReference(
        ref_id=1,
        ref_type=LegalRefType.ARTICLE_CODE,
        raw_text="article 1240 du Code civil",
        position=42,
    )
    assert r.ref_id == 1
    assert r.ref_type == LegalRefType.ARTICLE_CODE


def test_legal_reference_rejects_extra_keys():
    with pytest.raises(ValidationError, match="(extra|forbid|not permitted)"):
        LegalReference(
            ref_id=1,
            ref_type=LegalRefType.ARTICLE_CODE,
            raw_text="x",
            position=0,
            __html_payload="<script>",
        )


def test_verification_result_status_enum():
    """All status values from the spec are accepted."""
    valid = [
        "VERIFIE_EXACT", "VERIFIE_MINEUR", "PARTIELLEMENT_EXACT",
        "SUBSTANTIELLEMENT_ERRONE", "HALLUCINATION",
        "UNKNOWN_OPENLEGI_DISABLED", "UNKNOWN_AUTH_FAILED",
        "UNKNOWN_RATE_LIMITED", "UNKNOWN_NETWORK",
        "UNKNOWN_PARSE_ERROR",
    ]
    for s in valid:
        VerificationResult(status=s, score=0)


def test_verification_result_rejects_unknown_status():
    with pytest.raises(ValidationError):
        VerificationResult(status="WHATEVER", score=0)


def test_legal_hit_minimal():
    h = LegalHit(
        source="code",
        title="Code civil, Art. 1240",
        snippet="Tout fait quelconque…",
        url="https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000032041604/",
    )
    assert h.source == "code"
    assert h.score is None  # optional
