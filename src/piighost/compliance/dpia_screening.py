"""DPIA-lite screening (Art. 35) — detect triggers, emit verdict, prepare
inputs for the official CNIL PIA software.

We do NOT generate a full DPIA — that's CNIL's tool. We only screen
and pre-fill the inputs.

Triggers covered (6/9 from CNIL guidance):
  - art35.3.b   sensible à grande échelle
  - cnil_2      traitement à grande échelle
  - cnil_4      personnes vulnérables (santé)
  - cnil_5      usage innovant (IA/NER) — toujours présent (notre cas)
  - cnil_7      identité civile complète
  - cnil_9      données salariés (profession=rh)

Intentionally not implemented in this phase:
  - cnil_3 (recoupement de fichiers) — requires multi-project state
    crossing the per-project isolation boundary; deferred.
  - cnil_1 (évaluation/scoring) — semantic, requires intent labelling
    that we don't have yet.
  - cnil_6 (exclusion d'un service) — out of scope for the regulated
    professions targeted here.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from piighost.vault.store import Vault
    from piighost.vault.audit import AuditLogger

from piighost.service.models import (
    CNILPIAInputs, DPIAScreening, DPIATrigger,
)


# Art. 9 RGPD sensitive labels (same as processing_register)
_ART9_LABELS = {
    "donnee_sante", "donnee_biometrique", "donnee_genetique",
    "opinion_politique", "religion", "orientation_sexuelle",
    "origine_ethnique", "appartenance_syndicale", "condamnation_penale",
}

_LARGE_SCALE_THRESHOLD = 10000   # CNIL: traitement à grande échelle
_SENSITIVE_AT_SCALE_THRESHOLD = 100  # Art. 35.3.b: sensible à grande échelle


def screen_dpia(
    *,
    project_name: str,
    vault: "Vault",
    audit: "AuditLogger",
    profile: dict | None,
) -> DPIAScreening:
    """Run the DPIA-lite screening and return the result."""
    _profile = profile or {}
    stats = vault.stats()
    inventory = dict(stats.by_label or {})
    triggers: list[DPIATrigger] = []

    # Art. 35.3.b — sensible à grande échelle
    sensitive_total = sum(c for l, c in inventory.items() if l in _ART9_LABELS)
    if sensitive_total >= _SENSITIVE_AT_SCALE_THRESHOLD:
        sensitive_breakdown = [
            f"{l}: {c}" for l, c in inventory.items() if l in _ART9_LABELS
        ]
        triggers.append(DPIATrigger(
            code="art35.3.b",
            name="Données sensibles ou hautement personnelles à grande échelle",
            matched_evidence=sensitive_breakdown,
            severity="mandatory",
        ))

    # CNIL critère 2 — traitement à grande échelle
    if stats.total >= _LARGE_SCALE_THRESHOLD:
        triggers.append(DPIATrigger(
            code="cnil_2",
            name="Traitement à grande échelle",
            matched_evidence=[f"total: {stats.total} entités"],
            severity="high",
        ))

    # CNIL critère 4 — personnes vulnérables
    if "donnee_sante" in inventory:
        triggers.append(DPIATrigger(
            code="cnil_4",
            name="Données concernant des personnes vulnérables (santé)",
            matched_evidence=[f"donnee_sante: {inventory['donnee_sante']}"],
            severity="high",
        ))

    # CNIL critère 5 — usage innovant (IA/NER)
    triggers.append(DPIATrigger(
        code="cnil_5",
        name="Usage innovant: détection PII via modèle ML local (NER)",
        matched_evidence=["piighost utilise GLiNER2 + adaptateur français pour la détection"],
        severity="medium",
    ))

    # CNIL critère 7 — identité civile complète
    has_civil_id = (
        "nom_personne" in inventory and
        "lieu" in inventory and  # adresse approximée
        "numero_securite_sociale" in inventory
    )
    if has_civil_id:
        triggers.append(DPIATrigger(
            code="cnil_7",
            name="Données concernant l'identité civile complète",
            matched_evidence=["nom + lieu + numero_securite_sociale tous présents"],
            severity="high",
        ))

    # CNIL critère 9 — données salariés
    profession = _profile.get("controller", {}).get("profession", "")
    if profession == "rh":
        triggers.append(DPIATrigger(
            code="cnil_9",
            name="Données concernant des salariés (RH)",
            matched_evidence=[f"controller.profession = '{profession}'"],
            severity="high",
        ))

    # Verdict
    severities = [t.severity for t in triggers]
    if any(s == "mandatory" for s in severities) or severities.count("high") >= 2:
        verdict = "dpia_required"
        explanation = "Au moins un critère obligatoire ou ≥2 critères CNIL haute sévérité."
    elif "high" in severities:
        verdict = "dpia_recommended"
        explanation = "1 critère CNIL haute sévérité — DPIA recommandée."
    else:
        verdict = "dpia_not_required"
        explanation = "Aucun trigger Art. 35.3 mandatory. DPIA non requise mais documentation conseillée."

    # CNIL PIA inputs
    defaults = _profile.get("defaults", {})
    pia_inputs = CNILPIAInputs(
        processing_name=f"Dossier {project_name}",
        processing_description="Traitement de données dans le cadre de l'activité du cabinet",
        data_categories=sorted(inventory.keys()),
        data_subjects=["clients", "tiers contractants"]
            if profession != "rh" else ["salariés"],
        purposes=list(defaults.get("finalites") or []),
        legal_bases=list(defaults.get("bases_legales") or []),
        retention=str(defaults.get("duree_conservation_apres_fin_mission", "")),
        recipients=[],
        security_measures=[
            "Anonymisation à la source",
            "Détection PII locale (pas de transfert vers cloud externe pour inférence)",
        ],
    )

    report = DPIAScreening(
        generated_at=int(time.time()),
        project=project_name,
        data_inventory=inventory,
        triggers=triggers,
        verdict=verdict,
        verdict_explanation=explanation,
        cnil_pia_inputs=pia_inputs,
    )

    # Audit
    try:
        audit.record_v2(
            event_type="dpia_screened",
            project_id=project_name,
            metadata={
                "verdict": verdict,
                "n_triggers": len(triggers),
                "n_mandatory": sum(1 for s in severities if s == "mandatory"),
            },
        )
    except Exception:
        pass

    return report
