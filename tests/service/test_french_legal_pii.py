"""Tests for French legal PII anonymization using the RegexDetector.

Covers realistic French legal document scenarios:
- Numéro NIR (numéro de sécurité sociale)
- IBAN français
- Numéro de TVA intracommunautaire
- Numéro de téléphone français
- Email
- Multi-entité dans un document légal simulé

Uses RegexDetector (no GLiNER2) so these tests run in any CI environment.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from piighost.detector.regex import RegexDetector
from piighost.service import PIIGhostService, ServiceConfig


@pytest.fixture()
def vault_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".piighost"
    d.mkdir()
    (d / "config.toml").write_text("schema_version = 1\n", encoding="utf-8")
    return d


@pytest.fixture()
def regex_config() -> ServiceConfig:
    return ServiceConfig.model_validate(
        {
            "schema_version": 1,
            "detector": {"backend": "regex_only"},
            "embedder": {"backend": "none"},
            "safety": {"strict_rehydrate": False},
        }
    )


# ---------------------------------------------------------------------------
# French NIR (numéro de sécurité sociale)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fr_nir_anonymized(vault_dir, regex_config):
    """French NIR must be replaced with a FR_NIR placeholder."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        text = "Assuré : NIR 185057800604830 — dossier médical n°42."
        r = await svc.anonymize(text)
        assert "185057800604830" not in r.anonymized
        assert "<FR_NIR:" in r.anonymized
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_fr_nir_roundtrip(vault_dir, regex_config):
    """NIR anonymized then rehydrated must restore the original number."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        original = "Assuré : NIR 185057800604830 — dossier médical."
        anon = await svc.anonymize(original)
        assert "185057800604830" not in anon.anonymized
        rehydrated = await svc.rehydrate(anon.anonymized)
        assert "185057800604830" in rehydrated.text
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_fr_nir_invalid_key_not_detected(vault_dir, regex_config):
    """NIR with bad checksum key must NOT be detected."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        text = "Référence 185057800604899 invalide dans ce document."
        r = await svc.anonymize(text)
        assert "185057800604899" in r.anonymized, "Invalid NIR must not be anonymized"
    finally:
        await svc.close()


# ---------------------------------------------------------------------------
# IBAN français
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fr_iban_anonymized(vault_dir, regex_config):
    """French IBAN must be replaced with an IBAN_CODE placeholder."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        text = "Virement à effectuer sur IBAN FR76 3000 6000 0112 3456 7890 189."
        r = await svc.anonymize(text)
        assert "FR76" not in r.anonymized
        assert "<IBAN_CODE:" in r.anonymized
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_fr_iban_roundtrip(vault_dir, regex_config):
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        iban = "FR7630006000011234567890189"
        original = f"RIB : {iban}"
        anon = await svc.anonymize(original)
        assert iban not in anon.anonymized
        rehydrated = await svc.rehydrate(anon.anonymized)
        assert iban in rehydrated.text
    finally:
        await svc.close()


# ---------------------------------------------------------------------------
# TVA intracommunautaire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fr_vat_anonymized(vault_dir, regex_config):
    """French VAT number must be detected and anonymized."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        text = "Numéro de TVA intracommunautaire : FR12345678901"
        r = await svc.anonymize(text)
        assert "FR12345678901" not in r.anonymized
        assert "<EU_VAT:" in r.anonymized
    finally:
        await svc.close()


# ---------------------------------------------------------------------------
# Téléphone français
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fr_phone_international_anonymized(vault_dir, regex_config):
    """French phone (+33 prefix) must be detected and anonymized."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        text = "Contactez notre service au +33 6 12 34 56 78."
        r = await svc.anonymize(text)
        assert "+33 6 12 34 56 78" not in r.anonymized
        assert "<PHONE_NUMBER:" in r.anonymized
    finally:
        await svc.close()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_anonymized(vault_dir, regex_config):
    """Email addresses must be detected and anonymized."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        text = "Merci d'envoyer vos justificatifs à marie.dupont@cabinet-legis.fr."
        r = await svc.anonymize(text)
        assert "marie.dupont@cabinet-legis.fr" not in r.anonymized
        assert "<EMAIL_ADDRESS:" in r.anonymized
    finally:
        await svc.close()


# ---------------------------------------------------------------------------
# Document légal multi-entités
# ---------------------------------------------------------------------------


FRENCH_LEGAL_DOC = """\
CONTRAT DE PRESTATION DE SERVICES

Entre :
  M. Jean Dupont, salarié sous NIR 1 85 05 78 006 048 30,
  domicilié au 12 rue de la Paix, Paris,
  joignable au +33 1 42 68 53 00,
  email jean.dupont@avocat-paris.fr,

et :

  SARL LegiConseil, TVA intracommunautaire FR87432154789,
  dont le compte bancaire IBAN FR76 3000 6000 0112 3456 7890 189
  est ouvert à la Banque Postale.

Les parties conviennent des conditions suivantes...
"""


@pytest.mark.asyncio
async def test_legal_doc_no_pii_leaks(vault_dir, regex_config):
    """A realistic French legal document must have all regex PII replaced."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        r = await svc.anonymize(FRENCH_LEGAL_DOC)
        leaked = []
        for pii in (
            "185057800604830",
            "+33 1 42 68 53 00",
            "jean.dupont@avocat-paris.fr",
            "FR87432154789",
            "FR7630006000011234567890189",
        ):
            if pii.replace(" ", "") in r.anonymized.replace(" ", ""):
                leaked.append(pii)
        assert not leaked, f"PII still visible after anonymization: {leaked}"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_legal_doc_full_roundtrip(vault_dir, regex_config):
    """Anonymize then rehydrate must restore every PII value in the document."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        anon = await svc.anonymize(FRENCH_LEGAL_DOC)
        rehydrated = await svc.rehydrate(anon.anonymized)
        for pii in (
            "jean.dupont@avocat-paris.fr",
            "FR87432154789",
        ):
            assert pii in rehydrated.text, f"{pii!r} not restored after rehydration"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_legal_doc_entity_labels(vault_dir, regex_config):
    """Detected entities in the legal doc must carry expected labels."""
    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        r = await svc.anonymize(FRENCH_LEGAL_DOC)
        labels = {e.label for e in r.entities}
        assert "IBAN_CODE" in labels
        assert "EU_VAT" in labels
        assert "EMAIL_ADDRESS" in labels
        assert "PHONE_NUMBER" in labels
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_legal_doc_same_entity_same_placeholder(vault_dir, regex_config):
    """The same PII value detected twice must map to a single placeholder."""
    import re

    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        text = "Contact: marie@example.fr. Copie: marie@example.fr."
        r = await svc.anonymize(text)
        tokens = re.findall(r"<EMAIL_ADDRESS:[0-9a-f]+>", r.anonymized)
        assert len(tokens) == 2, "Both occurrences must produce a token"
        assert len(set(tokens)) == 1, "Same email must get the same placeholder token"
    finally:
        await svc.close()


# ---------------------------------------------------------------------------
# Multi-document cross-session consistency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_entity_across_documents(vault_dir, regex_config):
    """The same email in two different documents must resolve to the same token."""
    import re

    svc = await PIIGhostService.create(
        vault_dir=vault_dir,
        config=regex_config,
        detector=RegexDetector(),
    )
    try:
        r1 = await svc.anonymize("Expéditeur : marc@legis.fr", doc_id="doc1")
        r2 = await svc.anonymize("Destinataire : marc@legis.fr", doc_id="doc2")
        tok1 = re.search(r"<EMAIL_ADDRESS:[0-9a-f]+>", r1.anonymized)
        tok2 = re.search(r"<EMAIL_ADDRESS:[0-9a-f]+>", r2.anonymized)
        assert tok1 and tok2, "Email must be anonymized in both documents"
        assert tok1.group(0) == tok2.group(0), (
            "Same PII across documents must share the same placeholder token"
        )
    finally:
        await svc.close()
