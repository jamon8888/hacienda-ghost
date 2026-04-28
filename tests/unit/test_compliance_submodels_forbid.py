"""Sub-models in the compliance hierarchy must reject unknown keys.

Closes Phase 5 followup #2: top-level extra='forbid' alone leaves
sub-models permissive, which silently drops smuggled keys instead
of raising a clear ValidationError.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from piighost.service.models import (
    CNILPIAInputs,
    ControllerInfo,
    DataCategoryItem,
    DocumentsSummary,
    DPIATrigger,
    DPOInfo,
    ManualFieldHint,
    RetentionItem,
    SecurityMeasureItem,
    SubjectDocumentRef,
    SubjectExcerpt,
    TransferItem,
)


@pytest.mark.parametrize(
    "model_cls,minimal_kwargs",
    [
        (ControllerInfo, {"name": "X", "profession": "avocat"}),
        (DPOInfo, {"name": "Y"}),
        (DataCategoryItem, {"label": "email", "count": 1, "sensitive": False}),
        (RetentionItem, {"category": "factures", "duration": "10 ans"}),
        (TransferItem, {"destination": "US", "recipient": "X", "legal_mechanism": "SCC"}),
        (SecurityMeasureItem, {"name": "AES-256", "auto_detected": False}),
        (DocumentsSummary, {"total_docs": 0}),
        (ManualFieldHint, {"field": "X", "hint": "Y"}),
        (DPIATrigger, {"code": "art35.3.b", "name": "X", "severity": "mandatory"}),
        (CNILPIAInputs, {}),
        (SubjectDocumentRef, {"doc_id": "abc", "file_name": "x.pdf",
                              "file_path": "/x", "occurrences": 1}),
        (SubjectExcerpt, {"doc_id": "abc", "file_name": "x.pdf",
                          "chunk_index": 0, "redacted_text": ""}),
    ],
)
def test_submodel_rejects_extra_key(model_cls, minimal_kwargs):
    """Constructing each sub-model with an unknown extra key raises."""
    with pytest.raises(ValidationError, match="(extra|forbid|not permitted)"):
        model_cls(**minimal_kwargs, __html_payload="<script>")
