"""OutboundRedactor — the privacy boundary."""
from __future__ import annotations

import pytest

from piighost.legal.redactor import OutboundRedactor


def _stub_anonymize(text: str) -> str:
    """Replaces 'Marie Curie' / 'IBAN: FR…' / phone with [REDACTED]."""
    out = text
    out = out.replace("Marie Curie", "[REDACTED]")
    out = out.replace("FR1420041010050500013M02606", "[REDACTED]")
    out = out.replace("+33 6 12 34 56 78", "[REDACTED]")
    out = out.replace("marie@acme.fr", "[REDACTED]")
    return out


def test_redact_keeps_legal_grammar():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact("Marie Curie a invoqué l'article 1240 du Code civil.")
    # PII redacted
    assert "Marie Curie" not in out
    # Legal grammar preserved
    assert "article 1240" in out
    assert "Code civil" in out


def test_redact_keeps_pourvoi_number():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact("Cass. civ. 1re, 15 mars 2023, n°21-12.345 (Marie Curie c. Acme)")
    assert "21-12.345" in out
    assert "Cass" in out
    assert "Marie Curie" not in out


def test_redact_keeps_loi_number():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact("La loi n°78-17 du 6 janvier 1978 — Marie Curie est concernée.")
    assert "78-17" in out
    assert "1978" in out
    assert "Marie Curie" not in out


def test_redact_strips_iban_email_phone():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact(
        "IBAN FR1420041010050500013M02606, "
        "email marie@acme.fr, "
        "tél +33 6 12 34 56 78."
    )
    assert "FR1420041010050500013M02606" not in out
    assert "marie@acme.fr" not in out
    assert "+33 6 12 34 56 78" not in out


def test_redact_strips_pii_token_format():
    """Even our own placeholder format leaks pattern info — strip it."""
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact("article 1240 — sujet: <<nom_personne:abc12345>>")
    assert "<<nom_personne:abc12345>>" not in out
    assert "article 1240" in out


def test_redactor_hard_fails_on_anonymize_crash():
    """If anonymize_fn raises, the redactor raises — never silently proceed."""
    def crash(text):
        raise RuntimeError("anonymize boom")

    r = OutboundRedactor(anonymize_fn=crash)
    with pytest.raises(RuntimeError, match="boom"):
        r.redact("anything")


def test_redact_dict_payload():
    r = OutboundRedactor(anonymize_fn=_stub_anonymize)
    out = r.redact_dict({
        "search": "Marie Curie article 1240",
        "champ": "ARTICLE",
        "max_results": 5,
    })
    assert "Marie Curie" not in out["search"]
    assert "article 1240" in out["search"]
    # Non-string fields untouched
    assert out["max_results"] == 5
    assert out["champ"] == "ARTICLE"
