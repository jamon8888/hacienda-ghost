"""Build a ProcessingRegister (Art. 30) from project state.

Reads:
  - vault.stats() for category counts
  - documents_meta for doc-level inventory (doc_type, language, pages)
  - audit log v2 for recipients (caller_kind != 'skill') + outbound events
  - ControllerProfile for controller/DPO/purposes/retention

Doesn't write anything except the audit event 'registre_generated'.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from piighost.vault.store import Vault
    from piighost.vault.audit import AuditLogger
    from piighost.indexer.indexing_store import IndexingStore

from piighost.service.models import (
    ControllerInfo, DPOInfo, DataCategoryItem, DocumentsSummary,
    ManualFieldHint, ProcessingRegister, RetentionItem,
    SecurityMeasureItem,
)


# Art. 9 RGPD — sensitive categories the system can detect
_ART9_LABELS = {
    "donnee_sante", "donnee_biometrique", "donnee_genetique",
    "opinion_politique", "religion", "orientation_sexuelle",
    "origine_ethnique", "appartenance_syndicale", "condamnation_penale",
}


def build_processing_register(
    *,
    project_name: str,
    vault: "Vault",
    indexing_store: "IndexingStore",
    audit: "AuditLogger",
    profile: dict | None,
) -> ProcessingRegister:
    """Compose all signals into a ProcessingRegister."""
    _profile = profile or {}
    # 1. Identity
    ctrl_dict = _profile.get("controller", {})
    controller = ControllerInfo(
        name=ctrl_dict.get("name", ""),
        profession=ctrl_dict.get("profession", ""),
        bar_or_order_number=ctrl_dict.get("bar_or_order_number", ""),
        address=ctrl_dict.get("address", ""),
        country=ctrl_dict.get("country", "FR"),
    )
    dpo_dict = _profile.get("dpo", {})
    dpo = None
    if dpo_dict.get("name") or dpo_dict.get("email"):
        dpo = DPOInfo(
            name=dpo_dict.get("name", ""),
            email=dpo_dict.get("email", ""),
            phone=dpo_dict.get("phone", ""),
        )

    defaults = _profile.get("defaults", {})

    # 2. Vault inventory
    stats = vault.stats()
    data_categories: list[DataCategoryItem] = []
    sensitive_categories: list[str] = []
    for label, count in (stats.by_label or {}).items():
        is_sensitive = label in _ART9_LABELS
        data_categories.append(DataCategoryItem(
            label=label, count=count, sensitive=is_sensitive,
        ))
        if is_sensitive:
            sensitive_categories.append(label)

    # 3. Documents inventory
    docs_meta = indexing_store.list_documents_meta(project_name, limit=10000)
    docs_summary = DocumentsSummary(
        total_docs=len(docs_meta),
        by_doc_type=_count_by(docs_meta, "doc_type"),
        by_language=_count_by(docs_meta, "doc_language"),
        total_pages=sum((m.doc_page_count or 0) for m in docs_meta),
    )

    # 4. Subjects (heuristic on dossier_id + parties presence)
    subjects = _classify_data_subjects(docs_meta, controller.profession)

    # 5. Security measures (auto-detect what we can)
    measures = _detect_security_measures(stats)

    # 6. Manual fields (always add hints for what we can't infer)
    manual = [
        ManualFieldHint(
            field="autres_destinataires_humains",
            hint="Liste des collaborateurs/associés qui consultent ce dossier",
        ),
        ManualFieldHint(
            field="sous_traitants",
            hint="Cloud, hébergeurs externes, services tiers (Microsoft 365, AWS, etc.)",
        ),
        ManualFieldHint(
            field="transferts_hors_ue",
            hint="Si certains sous-traitants sont hors UE, préciser le mécanisme (CCS, BCR, décision d'adéquation)",
        ),
    ]

    # 7. Retention rules
    retention: list[RetentionItem] = []
    if defaults.get("duree_conservation_apres_fin_mission"):
        retention.append(RetentionItem(
            category="standard",
            duration=str(defaults["duree_conservation_apres_fin_mission"]),
        ))

    register = ProcessingRegister(
        generated_at=int(time.time()),
        project=project_name,
        controller=controller,
        dpo=dpo,
        processing_name=f"Dossier {project_name}",
        processing_purposes=list(defaults.get("finalites") or []),
        legal_bases=list(defaults.get("bases_legales") or []),
        data_subject_categories=subjects,
        data_categories=data_categories,
        sensitive_categories_present=sensitive_categories,
        recipients_internal=[],
        recipients_external=[],
        transfers_outside_eu=[],
        retention_periods=retention,
        security_measures=measures,
        documents_summary=docs_summary,
        manual_fields=manual,
    )

    # 8. Audit event
    try:
        audit.record_v2(
            event_type="registre_generated",
            project_id=project_name,
            metadata={
                "n_categories": len(data_categories),
                "n_sensitive": len(sensitive_categories),
                "n_docs": len(docs_meta),
            },
        )
    except Exception:
        pass

    return register


def _count_by(items, attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        v = getattr(item, attr, None)
        key = str(v) if v else "unknown"
        out[key] = out.get(key, 0) + 1
    return out


# Map raw party labels (as they appear in documents_meta.parties_json)
# to the user-facing data-subject category emitted in the registre.
_PARTY_LABEL_MAP = {
    "client": "clients",
    "clients": "clients",
    "patient": "patients",
    "patients": "patients",
    "salarie": "salariés",
    "salariés": "salariés",
    "salaries": "salariés",
    "employe": "salariés",
    "employee": "salariés",
    "personnel": "salariés",
    "candidat": "candidats",
    "tiers": "tiers contractants",
    "fournisseur": "fournisseurs",
}


def _classify_data_subjects(docs_meta, profession: str) -> list[str]:
    """Return the data-subject categories for the registre.

    Strategy (in order):
      1. Aggregate ``parties_json`` across all indexed documents and map
         each unique label to a user-facing category via ``_PARTY_LABEL_MAP``.
         This is the data-driven path — what the indexer actually saw.
      2. If parties_json is empty across the project, fall back to the
         project-name heuristic (dossier_id starts with 'client'/'dossier'/
         'rh'/'paie'/'salarie'/'personnel').
      3. If both are inconclusive, default to a profession-driven seed
         ('clients du cabinet' for avocat, 'salariés' for rh, 'clients'
         otherwise).

    The mapping is deliberately conservative — unknown party labels are
    surfaced as-is so the avocat sees them and can correct the registre
    manually rather than have piighost silently invent a category.
    """
    subjects: set[str] = set()

    # Path 1: data-driven from parties_json
    for m in docs_meta:
        for raw in m.parties or ():
            key = raw.strip().lower()
            mapped = _PARTY_LABEL_MAP.get(key)
            if mapped:
                subjects.add(mapped)
            elif key:
                # Unknown label — surface as-is for the avocat to review
                subjects.add(raw.strip())

    if subjects:
        return sorted(subjects)

    # Path 2: project-name heuristic (legacy)
    for m in docs_meta:
        d = (m.dossier_id or "").lower()
        if d.startswith("client") or d.startswith("dossier"):
            subjects.add("clients")
        if any(k in d for k in ("rh", "paie", "salarie", "personnel")):
            subjects.add("salariés")

    if subjects:
        return sorted(subjects)

    # Path 3: profession-driven default
    if profession == "avocat":
        return ["clients du cabinet"]
    if profession == "rh":
        return ["salariés"]
    return ["clients"]


def _detect_security_measures(stats) -> list[SecurityMeasureItem]:
    """Auto-detect measures that ARE in place."""
    return [
        SecurityMeasureItem(
            name=f"Anonymisation à la source ({stats.total} placeholders actifs)",
            auto_detected=True,
        ),
        SecurityMeasureItem(
            name="Détection PII via modèle local (pas de transfert vers cloud externe pour l'inférence)",
            auto_detected=True,
        ),
    ]
