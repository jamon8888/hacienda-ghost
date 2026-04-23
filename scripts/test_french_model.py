"""Smoke test for jamon8888/french-pii-legal-ner-quantized.

Usage:
    uv run python scripts/test_french_model.py

The quantized model is a full GLiNER2-large fine-tuned on French legal PII,
then serialized with torch.quantization.quantize_dynamic (INT8 linear weights).
Loading: base GLiNER2-large, quantize architecture, load INT8 state dict.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Windows CP1252 can't encode the brain emoji printed by GLiNER2's banner.
# Force UTF-8 on all streams before importing gliner2.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_MODEL   = "fastino/gliner2-large-v1"
ADAPTER_REPO = "jamon8888/french-pii-legal-ner-quantized"
WEIGHTS_FILE = "adapter_weights_int8.pt"
THRESHOLD    = 0.40

# French model label -> piighost external label
LABEL_MAP: dict[str, str] = {
    "nom_personne":             "PERSON",
    "prenom":                   "PERSON",
    "avocat":                   "PERSON",
    "juge":                     "PERSON",
    "notaire":                  "PERSON",
    "profession":               "PROFESSION",
    "adresse":                  "ADDRESS",
    "lieu":                     "LOC",
    "lieu_naissance":           "LOC",
    "organisation":             "ORG",
    "tribunal":                 "ORG",
    "date":                     "DATE",
    "date_naissance":           "DATE",
    "email":                    "EMAIL",
    "numero_telephone":         "PHONE",
    "numero_compte_bancaire":   "IBAN",
    "numero_siret":             "SIRET",
    "numero_securite_sociale":  "SSN",
    "numero_carte_identite":    "ID",
    "numero_passeport":         "PASSPORT",
    "numero_affaire":           "CASE_NUMBER",
    "plaque_immatriculation":   "LICENSE_PLATE",
    "salaire":                  "SALARY",
    "nationalite":              "NATIONALITY",
    "donnee_sante":             "HEALTH",
    "donnee_biometrique":       "BIOMETRIC",
    "donnee_genetique":         "GENETIC",
    "opinion_politique":        "POLITICAL_OPINION",
    "religion":                 "RELIGION",
    "origine_ethnique":         "ETHNIC_ORIGIN",
    "orientation_sexuelle":     "SEXUAL_ORIENTATION",
    "condamnation_penale":      "CRIMINAL",
    "base_legale_traitement":   "LEGAL_BASIS",
    "appartenance_syndicale":   "TRADE_UNION",
}

SAMPLES = [
    (
        "contrat",
        "M. Jean-Pierre Dupont, né le 14 mars 1978 à Lyon, demeurant au 12 rue des Lilas, "
        "75011 Paris, titulaire du passeport n° FR123456, est embauché par la société "
        "TechCorp SAS (SIRET 55204944776279) en qualité d'ingénieur logiciel pour un "
        "salaire brut mensuel de 4 500 euros. Contacter M. Dupont à jean.dupont@mail.fr ou "
        "au 06 12 34 56 78.",
    ),
    (
        "jugement",
        "Le Tribunal de Grande Instance de Paris, dans l'affaire n° 2024/03421, "
        "opposant la SAS Nexus Technologies à M. Ahmed Benali, représenté par "
        "Maître Sophie Leclerc, avocat au barreau de Paris, sous la présidence "
        "du juge Mme Isabelle Moreau, rend le jugement suivant.",
    ),
    (
        "medical",
        "La patiente Mme Fatima El Amrani (née le 03/07/1985, NSS 285076912345678) "
        "présente une pathologie cardiaque documentée. Son numéro de compte bancaire "
        "FR76 3000 6000 0112 3456 7890 189 est utilisé pour le remboursement mutuelle. "
        "Son véhicule immatriculé AB-123-CD a été signalé lors de l'incident.",
    ),
    (
        "syndicat",
        "M. François Dupont, délégué syndical CGT au sein de Renault SA depuis "
        "janvier 2015, a saisi le tribunal prud'homal concernant son appartenance "
        "syndicale et les discriminations subies de ce fait par son employeur.",
    ),
]


def load_model():
    """Load INT8-quantized GLiNER2 with active LoRA encoder.

    The checkpoint was produced by:
      1. GLiNER2.from_pretrained(base)
      2. load_lora_adapter(model, adapter)   ← LoRA layers injected into encoder
      3. quantize_dynamic(model, {Linear})   ← base_layer inside LoRA → INT8;
                                               task heads → INT8
      4. torch.save(model.state_dict())

    To load, we must mirror that exact construction order so the architecture
    matches the state-dict key structure before calling load_state_dict.
    """
    import torch
    from gliner2 import GLiNER2
    from gliner2.training.lora import apply_lora_to_model, LoRAConfig
    from huggingface_hub import hf_hub_download

    print(f"1/4  Loading base model: {BASE_MODEL}")
    model = GLiNER2.from_pretrained(BASE_MODEL)

    print("2/4  Injecting LoRA structure into encoder (r=16, alpha=32)...")
    lora_config = LoRAConfig(
        enabled=True, r=16, alpha=32.0, dropout=0.0, target_modules=["encoder"]
    )
    model, _ = apply_lora_to_model(model, lora_config)

    print("3/4  Quantizing architecture (INT8 dynamic)...")
    torch.quantization.quantize_dynamic(
        model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True
    )

    print(f"4/4  Loading fine-tuned INT8 weights from {ADAPTER_REPO}...")
    weights_path = hf_hub_download(ADAPTER_REPO, WEIGHTS_FILE)
    state_dict = torch.load(weights_path, map_location="cpu", weights_only=False)
    model.load_state_dict(state_dict)
    model.eval()
    print("     Model ready.\n")
    return model


async def main() -> None:
    try:
        import gliner2  # noqa: F401
    except ImportError:
        print("ERROR: gliner2 not installed. Run: uv pip install piighost[gliner2]")
        return

    model = load_model()

    from piighost.detector.gliner2 import Gliner2Detector
    from piighost.anonymizer import Anonymizer
    from piighost.linker.entity import ExactEntityLinker
    from piighost.pipeline.base import AnonymizationPipeline
    from piighost.placeholder import HashPlaceholderFactory
    from piighost.resolver.entity import MergeEntityConflictResolver
    from piighost.resolver.span import ConfidenceSpanConflictResolver

    # Pass all 33 French labels as a list — each label maps to itself.
    # The placeholder will read e.g. <nom_personne:abc123>.
    french_labels = list(LABEL_MAP.keys())

    # Run at two thresholds so we can see what's hiding just below the cut.
    for threshold in (0.40, 0.30):
        detector = Gliner2Detector(
            model=model,
            labels=french_labels,
            threshold=threshold,
        )
        pipeline = AnonymizationPipeline(
            detector=detector,
            span_resolver=ConfidenceSpanConflictResolver(),
            entity_linker=ExactEntityLinker(),
            entity_resolver=MergeEntityConflictResolver(),
            anonymizer=Anonymizer(HashPlaceholderFactory()),
        )

        print(f"\n{'=' * 70}")
        print(f"THRESHOLD = {threshold}")
        print('=' * 70)

        for name, text in SAMPLES:
            print(f"\n[{name.upper()}]")
            print(f"Input : {text[:120]}{'...' if len(text) > 120 else ''}")

            detections = await detector.detect(text)
            detections_sorted = sorted(detections, key=lambda d: d.position.start_pos)

            print(f"\nDetections ({len(detections_sorted)}):")
            for d in detections_sorted:
                ext = LABEL_MAP.get(d.label, d.label)
                print(f"  {d.label:35s} → {ext:20s} {d.confidence:.2f}  {d.text!r}")

            anonymized, _ = await pipeline.anonymize(text)
            print(f"\nAnonymized:\n  {anonymized[:200]}{'...' if len(anonymized) > 200 else ''}")
            print("-" * 70)


if __name__ == "__main__":
    asyncio.run(main())
