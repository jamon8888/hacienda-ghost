# RGPD Compliance opérationnelle — design

**Date:** 2026-04-27
**Status:** Spec — awaiting plan
**Scope:** Phase 0 (Foundation) + Phase 1 (Droits RGPD) + Phase 2 (Registre Art. 30 + DPIA-lite + Render)

## Problem

Le plugin hacienda + serveur MCP piighost a un cœur solide (détection PII, RAG redacté,
audit basic). Pour qu'un avocat, notaire, médecin, expert-comptable ou DPO puisse
l'utiliser **en production conforme** — c'est-à-dire défendable devant la CNIL ou un
juge — il manque le bloc "compliance opérationnelle" :

1. **Droits Art. 15** (accès) : "Mme Dupont demande ce que vous avez sur elle" → on ne
   sait pas répondre proprement aujourd'hui (pas de moyen de retrouver toutes les
   références à une même personne).
2. **Droits Art. 17** (oubli) : "Mme Dupont demande l'effacement" → on ne sait pas
   purger sans tout réindexer + on n'a pas la trace de l'effacement.
3. **Registre Art. 30** : aucun outil n'aggrège ce qui est traité dans un dossier en
   un document conforme.
4. **DPIA Art. 35** : aucune aide pour décider si une DPIA est requise et préparer ses
   inputs.

Cette spec couvre ces 4 manques en s'appuyant sur les briques existantes (vault SQLite
+ `doc_entities` table, audit log, GLiNER2, kreuzberg metadata) sans introduire de
backend cloud ni de modèle ML supplémentaire.

## Goals

- **Subject access (Art. 15)** : retrouver tous les tokens liés à une personne via un
  algorithme de clustering déterministe basé sur la table `doc_entities` existante,
  produire un rapport structuré + livrable PDF/DOCX/MD.
- **Right to be forgotten (Art. 17) avec tombstone** : purger une personne du vault et
  des chunks indexés, mais conserver dans l'audit un événement `forgotten` (avec hash
  du token, jamais le token lui-même) — défendable Art. 17.3 + Art. 30.
- **Registre Art. 30** : générer un document décrivant le traitement (catégories,
  finalités, durées, destinataires, transferts, mesures de sécurité) à partir de
  données réelles déjà dans le vault et l'audit log.
- **DPIA-lite** : screening qui détecte les triggers Art. 35.3 + lignes directrices
  CNIL et redirige vers l'outil officiel CNIL ([PIA](https://www.cnil.fr/fr/outil-pia-telechargez-et-installez-le-logiciel-de-la-cnil))
  avec inputs pré-remplis.
- **Foundation reposable** : per-document metadata (doc_type, doc_date, doc_title,
  language, parties, dossier_id), audit event v2 versionné, profil du responsable de
  traitement (`~/.piighost/controller.toml`).
- **Render layer séparé** : data structurée (dict) découplée de la présentation (PDF /
  DOCX / MD via Jinja2), templates par profession (avocat, notaire, médecin,
  expert-comptable, RH).

## Non-goals

- **Pas de DPIA complète auto-générée** : on s'arrête au screening. La CNIL fournit le
  PIA software officiel ; le reproduire est une duplication concurrentielle douteuse.
- **Pas de chiffrement at-rest du vault** dans cette spec — c'est sub-projet #7 du
  brainstorm initial, à faire avant déploiement prod mais hors scope ici.
- **Pas de hash chain forensique de l'audit** — on prépare le terrain (`event_hash`
  + `prev_hash` dans le schéma) mais la vérification d'intégrité est sub-projet #5.
- **Pas de multi-utilisateur** — `actor` capturé via `os.getlogin()`, à upgrader
  quand on adresse RBAC.
- **Pas de notification de violation 72h** — workflow externe (mail/SMS au DPO + CNIL),
  hors stack MCP.
- **Pas de citations Légifrance** — sub-projet #6 du brainstorm initial, séparé.
- **Pas de filtres temporels query / détection clauses / récap dossier** — Phases 3-5
  du brainstorm initial, à venir dans des specs séparées.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ Plugin hacienda v0.5.0                                               │
│   Skills:                                                            │
│     • setup            (slash: /hacienda:setup) — onboarding wizard  │
│     • rgpd-access      (slash: /hacienda:rgpd:access)                │
│     • rgpd-forget      (slash: /hacienda:rgpd:forget)                │
│     • rgpd-registre    (slash: /hacienda:rgpd:registre)              │
│     • rgpd-dpia        (slash: /hacienda:rgpd:dpia)                  │
└──────────────────────────────────────────────────────────────────────┘
                               │ MCP
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ piighost MCP server (8 nouveaux tools)                                │
│   Phase 0 (foundation):                                              │
│     • controller_profile_get / set                                   │
│   Phase 1 (droits):                                                  │
│     • cluster_subjects(query, project)                               │
│     • subject_access(tokens, project)                                │
│     • forget_subject(tokens, project, dry_run, legal_basis)          │
│   Phase 2 (registre/DPIA/render):                                    │
│     • processing_register(project)                                   │
│     • dpia_screening(project)                                        │
│     • render_compliance_doc(data, format, profile, output_path)      │
└──────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ piighost daemon (PIIGhostService)                                    │
│   _ProjectService:                                                   │
│     + DocumentMetadataExtractor (kreuzberg + GLiNER2 + heuristics)   │
│     + AuditEvent v2 (versioned schema, prev_hash, event_id)          │
│     + subject_clustering (pure SQL on doc_entities)                  │
│     + subject_access / forget_subject (cascade with tombstone)       │
│     + processing_register / dpia_screening                           │
│   Global:                                                            │
│     + ControllerProfileService (~/.piighost/controller.toml +        │
│       per-project overrides)                                         │
│     + Render layer (compliance/templates/<profile>/*.j2)             │
└──────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Storage                                                              │
│   Existing reused:                                                   │
│     • vault/entities (token → original)                              │
│     • vault/doc_entities (doc_id ↔ token, position) ← KEY FIND       │
│     • indexer/indexed_files                                          │
│     • LanceDB chunks                                                 │
│     • audit.log (v1 → v2 reader, append-only)                        │
│   New:                                                               │
│     • indexer/documents_meta (doc_type, doc_date, doc_title,         │
│       doc_language, parties, dossier_id, …)                          │
│     • ~/.piighost/controller.toml                                    │
│     • ~/.piighost/projects/<p>/controller_overrides.toml             │
│     • ~/.piighost/templates/<profile>/*.j2 (override path)           │
│     • piighost.compliance.templates/ (bundled defaults)              │
└──────────────────────────────────────────────────────────────────────┘
```

**Principes** :

1. **Phase 0 déverrouille tout** — `documents_meta` et `AuditEvent v2` sont consommés
   par les Phases 1 et 2.
2. **Pas de backend supplémentaire** — tout reste en SQLite + un fichier TOML
   user-level + des templates Jinja2.
3. **Render découplé du data layer** — les outils compliance retournent du dict
   versionné. La conversion PDF/DOCX/MD passe par `render_compliance_doc(data, format,
   profile)`.
4. **Migration audit v1 → v2 zero-downtime** — le reader détecte la version par ligne.
   Pas de réécriture du fichier ; new events en v2, existants en v1.
5. **Réutilisation maximale du SQL existant** — la table `doc_entities` (lien
   `(doc_id, token, start_pos, end_pos)`) déjà alimentée par l'indexeur évite tout
   nouveau full-text search ou scan de chunks pour le clustering / subject_access /
   forget.

## Phase 0 — Foundation

### Document metadata (extraction à l'indexation)

`DocumentMetadata` Pydantic dans `service/models.py` :

```python
class DocumentMetadata(BaseModel):
    doc_id: str
    doc_type: Literal[
        "contrat", "facture", "email", "courrier", "acte_notarie",
        "jugement", "decision_administrative", "attestation",
        "cv", "note_interne", "autre",
    ] = "autre"
    doc_type_confidence: float = 0.0
    doc_date: int | None = None         # epoch seconds
    doc_date_source: Literal[
        "kreuzberg_creation", "kreuzberg_modified",
        "heuristic_detected", "filename", "none",
    ] = "none"
    # Free metadata from kreuzberg (FLAT in v4.9.4 — not nested under "pdf")
    doc_title: str | None = None
    doc_subject: str | None = None       # PDF subject field
    doc_authors: list[str] = []          # kreuzberg returns list
    doc_language: str | None = None      # auto-detected
    doc_page_count: int | None = None
    doc_format: str = ""                 # "pdf"/"docx"/"html"/"plain"/etc.
    is_encrypted_source: bool = False    # kreuzberg flag
    # Project semantics
    parties: list[str] = []              # nom_personne + organisation tokens
    dossier_id: str = ""                 # first sub-folder under project root
    extracted_at: int                    # when this row was written
```

### `documents_meta` SQLite table

Co-localisée avec `indexed_files` dans `indexing.sqlite` :

```sql
CREATE TABLE IF NOT EXISTS documents_meta (
    project_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'autre',
    doc_type_confidence REAL NOT NULL DEFAULT 0.0,
    doc_date INTEGER,
    doc_date_source TEXT NOT NULL DEFAULT 'none',
    doc_title TEXT,
    doc_subject TEXT,
    doc_authors_json TEXT NOT NULL DEFAULT '[]',
    doc_language TEXT,
    doc_page_count INTEGER,
    doc_format TEXT NOT NULL DEFAULT '',
    is_encrypted_source INTEGER NOT NULL DEFAULT 0,
    parties_json TEXT NOT NULL DEFAULT '[]',
    dossier_id TEXT NOT NULL DEFAULT '',
    extracted_at REAL NOT NULL,
    PRIMARY KEY (project_id, doc_id)
);

CREATE INDEX idx_docmeta_dossier   ON documents_meta(project_id, dossier_id);
CREATE INDEX idx_docmeta_doctype   ON documents_meta(project_id, doc_type);
CREATE INDEX idx_docmeta_date      ON documents_meta(project_id, doc_date);
CREATE INDEX idx_docmeta_language  ON documents_meta(project_id, doc_language);
```

### Pipeline d'extraction (corrigé pour kreuzberg v4.9.4 flat metadata)

`indexer/ingestor.py` modifié pour exposer `(text, metadata_dict)` :

```python
async def extract_with_metadata(path: Path) -> tuple[str | None, dict]:
    """Extract text + raw metadata. Plain text → empty metadata."""
    if path.suffix.lower() in _PLAIN_TEXT_EXTENSIONS:
        text = _read_plain_text(path)
        return text, {}
    import kreuzberg
    try:
        result = await kreuzberg.extract_file(path)
        return result.content, dict(result.metadata or {})  # FLAT dict
    except Exception:
        return None, {}
```

`service/doc_metadata_extractor.py` (NEW) :

```python
def build_metadata(
    *, doc_id: str,
    file_path: Path,
    project_root: Path,
    content: str,
    kreuzberg_meta: dict,
    detections: list[Detection],
) -> DocumentMetadata:
    """Stitch kreuzberg + GLiNER2 + heuristics into one DocumentMetadata."""

    # doc_date: priorité kreuzberg → heuristique
    doc_date, source = pick_doc_date(kreuzberg_meta, content, detections)

    # doc_type: heuristique structurelle (Phase 0 baseline; GLiNER2 fallback later)
    from piighost.service.doc_type_classifier import classify
    doc_type, conf = classify(
        file_path.name, content[:1500],
        title_hint=kreuzberg_meta.get("title"),
        format_hint=kreuzberg_meta.get("format_type"),
    )

    return DocumentMetadata(
        doc_id=doc_id,
        doc_type=doc_type,
        doc_type_confidence=conf,
        doc_date=doc_date,
        doc_date_source=source,
        doc_title=kreuzberg_meta.get("title"),
        doc_subject=kreuzberg_meta.get("subject"),
        doc_authors=kreuzberg_meta.get("authors") or [],
        doc_language=kreuzberg_meta.get("language"),
        doc_page_count=kreuzberg_meta.get("page_count"),
        doc_format=(kreuzberg_meta.get("format_type") or "").lower(),
        is_encrypted_source=bool(kreuzberg_meta.get("is_encrypted")),
        parties=[d.token for d in detections
                 if d.label in {"nom_personne", "organisation", "prenom"}],
        dossier_id=_extract_dossier_id(file_path, project_root),
        extracted_at=int(time.time()),
    )


def pick_doc_date(meta: dict, content: str, detections: list[Detection]) -> tuple[int | None, str]:
    """1. kreuzberg created_at (ISO) → 2. modified_at → 3. detected dates heuristic."""
    iso = meta.get("created_at") or meta.get("creation_date")
    if iso:
        return _parse_iso_to_epoch(iso), "kreuzberg_creation"
    iso = meta.get("modified_at") or meta.get("modification_date")
    if iso:
        return _parse_iso_to_epoch(iso), "kreuzberg_modified"
    # Heuristic fallback on detected GLiNER2 dates
    epoch = _score_detected_dates(detections, content)
    if epoch is not None:
        return epoch, "heuristic_detected"
    return None, "none"
```

### `doc_type_classifier` (heuristique structurelle, baseline E)

`service/doc_type_classifier.py` (NEW, pure function, no I/O) :

```python
def classify(
    filename: str, text_head: str, *,
    title_hint: str | None = None, format_hint: str | None = None,
) -> tuple[DocType, float]:
    """Returns (doc_type, confidence in [0.0, 1.0])."""
```

Cascade : (1) regex sur filename → (2) regex structurels sur `text_head` →
(3) hints kreuzberg (title/format) → (4) `("autre", 0.0)`.

Tableau de patterns module-level — facilement éditable, pas de modèle.

### AuditEvent v2 (avec hash chain en préparation, vérification non scope)

`vault/audit.py` étendu :

```python
class AuditEvent(BaseModel):
    v: Literal[2] = 2
    event_id: str                  # uuid4 hex
    event_type: str                # rehydrate | query | subject_access | forgotten | …
    timestamp: float
    actor: str = "user"            # os.getlogin() — Phase 0 stub for multi-user
    project_id: str
    subject_token: str | None = None
    metadata: dict = Field(default_factory=dict)
    prev_hash: str | None = None   # hash chain (recorded but verification future)
    event_hash: str                # sha256 of canonical_json without event_hash itself
```

`AuditLogger.record(...)` reçoit déjà `metadata: dict` aujourd'hui — on lui ajoute le
calcul de `event_hash`/`prev_hash` et la version v2. Lecture v1 → reader synthétique
remonte les events legacy en v2 sans modification de fichier.

### ControllerProfile (`~/.piighost/controller.toml`)

```toml
[controller]
name = "Cabinet Dupont & Associés"
profession = "avocat"
bar_or_order_number = "B12345"
address = "1 rue de la Paix, 75001 Paris"
country = "FR"

[dpo]
name = "Marie Lefevre"
email = "dpo@dupont-associes.fr"
phone = "+33123456789"

[defaults]
finalites = ["Conseil juridique aux clients", "Représentation en justice"]
bases_legales = ["execution_contrat", "obligation_legale"]
duree_conservation_apres_fin_mission = "5 ans"
```

`service/controller_profile.py` charge global + override per-project (deep merge) ;
écrit atomiquement via tempfile + os.replace.

## Phase 1 — Droits RGPD

### Subject clustering (basé sur `doc_entities`, pas de full-text search)

Table existante `vault/doc_entities (doc_id, token, start_pos, end_pos)` rend le
clustering trivial via SQL :

```python
def cluster_subjects(query: str, project: str) -> list[SubjectCluster]:
    # 1. Find seed tokens matching the query text via vault.search_entities
    seeds = vault.search_entities(query, limit=20)
    if not seeds:
        return []

    # 2. For each seed, find docs containing it
    # 3. Co-occurrence: tokens in those docs grouped by frequency
    cooccurrence_sql = """
        SELECT de2.token, COUNT(DISTINCT de1.doc_id) AS shared_docs
        FROM doc_entities de1
        JOIN doc_entities de2 USING (doc_id)
        WHERE de1.token = ? AND de2.token != ?
        GROUP BY de2.token
        ORDER BY shared_docs DESC
    """

    # 4. Cluster: tokens that co-occur with the seed in ≥ N docs
    # 5. Compute confidence = shared_docs / total_docs_for_seed
```

Retourne `list[SubjectCluster]` avec `tokens`, `confidence`, `sample_doc_ids`,
`first_seen`, `last_seen`. L'avocat valide quel(s) cluster(s) traiter.

**Implémentation** : pure SQL sur le schéma vault existant + 1 nouvelle méthode :

```python
# vault/store.py — NEW method
def docs_containing_tokens(self, tokens: list[str]) -> list[str]:
    """Return distinct doc_ids that contain at least one of the given tokens."""
    placeholders = ",".join("?" * len(tokens))
    rows = self._conn.execute(
        f"SELECT DISTINCT doc_id FROM doc_entities WHERE token IN ({placeholders})",
        tokens,
    ).fetchall()
    return [r[0] for r in rows]


def cooccurring_tokens(self, seed_token: str) -> list[tuple[str, int]]:
    """Return (token, shared_doc_count) pairs co-occurring with seed."""
    rows = self._conn.execute(
        """
        SELECT de2.token, COUNT(DISTINCT de1.doc_id) AS shared
        FROM doc_entities de1 JOIN doc_entities de2 USING (doc_id)
        WHERE de1.token = ? AND de2.token != ?
        GROUP BY de2.token ORDER BY shared DESC
        """,
        (seed_token, seed_token),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]
```

### `subject_access(tokens, project)` — Art. 15

Output structuré (dict) — `SubjectAccessReport` Pydantic :

```python
class SubjectAccessReport(BaseModel):
    v: Literal[1] = 1
    generated_at: int
    project: str
    subject_tokens: list[str]
    subject_preview: list[str]               # ["M*****t (nom_personne)", …]
    categories_found: dict[str, int]         # {"nom_personne": 5, "email": 3, …}
    documents: list[SubjectDocumentRef]      # via documents_meta join
    processing_purpose: str                  # depuis ControllerProfile
    legal_basis: str
    retention_period: str
    third_party_recipients: list[str]        # depuis audit log structuré
    transfers_outside_eu: list[str]
    excerpts: list[SubjectExcerpt]           # chunks redactés
    excerpts_truncated: bool
    total_excerpts: int
```

**Implémentation** :

```python
async def subject_access(self, tokens: list[str], *, max_excerpts: int = 50):
    # 1. doc_ids containing any of the tokens (vault SQL — instant)
    doc_ids = self._vault.docs_containing_tokens(tokens)

    # 2. Join documents_meta for richer doc info
    doc_refs = self._indexing_store.documents_meta_for(self._project_name, doc_ids)

    # 3. Categories: lookup vault entries for each token, group by label
    categories = self._categorize(tokens)

    # 4. ControllerProfile for purpose/legal/retention
    profile = await self._service.get_controller_profile(self._project_name)

    # 5. Recipients: scan audit log v2 for events with project + token in metadata
    recipients_internal, recipients_external = self._extract_recipients(tokens)
    transfers = self._extract_eu_transfers(tokens)

    # 6. Excerpts: chunks containing any token, position-aware via doc_entities
    excerpts = self._build_redacted_excerpts(doc_ids, tokens, max_excerpts)

    # 7. AuditEvent v2 type=subject_access
    await self._audit.record_v2(
        event_type="subject_access",
        subject_token=tokens[0],
        metadata={"cluster_size": len(tokens), "n_docs": len(doc_refs)},
    )
    return SubjectAccessReport(...)
```

### `forget_subject(tokens, project, dry_run, legal_basis)` — Art. 17 (tombstone)

```python
async def forget_subject(
    self, tokens: list[str], *,
    dry_run: bool = True,
    legal_basis: Literal[
        "a-finalité_atteinte",
        "b-retrait_consentement",
        "c-opposition",
        "d-traitement_illicite",
        "e-obligation_legale",
        "f-mineur",
    ] = "c-opposition",
) -> ForgetReport:
    affected_doc_ids = self._vault.docs_containing_tokens(tokens)
    affected_chunks = self._chunk_store.chunks_for_doc_ids(affected_doc_ids)

    if dry_run:
        return ForgetReport(dry_run=True, ...)

    # 1. Rewrite chunks: replace each token by <<deleted:HASH8>>
    rewritten = []
    for chunk in affected_chunks:
        new_text = chunk["text"]
        for tok in tokens:
            tomb = f"<<deleted:{sha256(tok.encode())[:8]}>>"
            new_text = new_text.replace(tok, tomb)
        rewritten.append((chunk, new_text))

    # 2. Re-embed rewritten chunks (context changed)
    new_vectors = await self._embedder.embed([t for _, t in rewritten])

    # 3. Update LanceDB chunks + rebuild BM25
    self._chunk_store.update_chunks(rewritten, new_vectors)
    self._bm25.rebuild(self._chunk_store.all_records())

    # 4. Purge vault entries (entities + doc_entities for those tokens)
    purged_count = 0
    for tok in tokens:
        purged_count += self._vault.delete_token(tok)  # NEW method

    # 5. Audit tombstone — hashes only, never raw tokens
    await self._audit.record_v2(
        event_type="forgotten",
        metadata={
            "tokens_purged_hashes": [sha256(t.encode())[:8] for t in tokens],
            "n_chunks_rewritten": len(rewritten),
            "n_docs_affected": len(affected_doc_ids),
            "legal_basis": legal_basis,
            "operator_actor": os.getlogin(),
        },
    )
    return ForgetReport(dry_run=False, ...)
```

`Vault.delete_token(token)` (NEW) — supprime de `entities` + `doc_entities` en
transaction.

## Phase 2 — Registre Art. 30 + DPIA-lite + Render

### `processing_register(project)`

`ProcessingRegister` consomme `vault_stats`, `documents_meta`, `audit log v2` et
`ControllerProfile`. Détaillé dans le code spec (voir Phase 2 Section 4 du
brainstorm) :

- Identité responsable + DPO depuis `ControllerProfile`
- Catégories de personnes concernées (heuristique sur `dossier_id` + `parties`)
- Catégories de données (depuis `vault_stats`)
- Sensibles Art. 9 (mapping label → catégorie sensible)
- Destinataires (depuis audit log : `caller_kind != "skill"` + outbound events)
- Transferts hors UE (depuis outbound events)
- Durées de conservation (depuis ControllerProfile, override per-doctype possible)
- Mesures de sécurité (auto-détectées : chiffrement, audit chain, anonymisation
  active)
- Inventaire docs (depuis `documents_meta`: par doc_type, par language, page_count
  total)
- `manual_fields` : champs à compléter avec hints

Audit event `registre_generated` enregistré.

### `dpia_screening(project)` (DPIA-lite + redirect CNIL)

Évalue les triggers Art. 35.3 + 9 critères CNIL :

| Code | Critère | Détection auto |
|---|---|---|
| art35.3.b | Données sensibles à grande échelle | `sensitive_labels in vault AND total > 100` |
| cnil_2 | Grande échelle | `total > 10000` |
| cnil_3 | Recoupement de fichiers | `n_projects > 1 with overlapping subjects` |
| cnil_4 | Personnes vulnérables | `donnee_sante OR mineur detected` |
| cnil_5 | Usage innovant (IA/NER) | Toujours TRUE (notre cas !) |
| cnil_7 | Identité civile complète | `nom + adresse + numero_securite_sociale` co-occurrent |
| cnil_9 | Données salariés (RH) | `dossier_id contient "rh|paie|salarie"` OR `controller.profession == "rh"` |

Verdict : `dpia_required` (mandatory ≥1 OR high ≥2) / `dpia_recommended` / `dpia_not_required`.

Output inclut `cnil_pia_inputs` — JSON exportable importable dans le PIA software CNIL.

### `render_compliance_doc(data, format, profile, output_path)`

Couche de présentation séparée. Détecte le doctype depuis `data["v"]` + shape ;
charge le template `~/.piighost/templates/<profile>/<doctype>.<format>.j2` (ou
fallback bundled `piighost.compliance.templates/`) ; rend en MD / DOCX
(`docxtpl`) / PDF (`weasyprint` via Markdown → HTML → PDF).

Templates bundled (`src/piighost/compliance/templates/`) :

```
generic/   subject_access.md.j2  registre.md.j2  dpia_screening.md.j2
avocat/    subject_access.md.j2  registre.md.j2
notaire/   registre.md.j2
medecin/   registre.md.j2
expert_comptable/  registre.md.j2
rh/        registre.md.j2
```

L'utilisateur peut overrider dans `~/.piighost/templates/<profile>/`.

Nouvelles deps optionnelles (`[project.optional-dependencies] compliance`) :

```toml
[project.optional-dependencies]
compliance = ["Jinja2>=3.1", "docxtpl>=0.16", "weasyprint>=62", "markdown>=3.5"]
```

## Wizard `/hacienda:setup`

Skill `setup` dans le plugin. Déclenchée manuellement ou auto à la 1re utilisation
d'un tool RGPD si `~/.piighost/controller.toml` n'existe pas.

Workflow conversationnel en 6 étapes :

1. Profession (avocat / notaire / EC / médecin / RH / autre)
2. Identité cabinet (nom, adresse, pays)
3. N° d'inscription ordinal (barreau / chambre / OEC / ARS)
4. DPO (oui/non/inconnu — wizard détermine si obligatoire)
5. Finalités habituelles (défauts pré-remplis par profession, éditables)
6. Durée de conservation par défaut (recommandation par profession)

Résultat : `~/.piighost/controller.toml` créé via `mcp__piighost__controller_profile_set`.

Mode override per-project : `/hacienda:setup --project <name>` charge le global,
demande seulement les champs à surcharger, écrit dans
`~/.piighost/projects/<p>/controller_overrides.toml`.

Profils bundled (defaults TOML par profession) :

```
src/piighost/compliance/profiles/
  avocat.toml  notaire.toml  expert_comptable.toml
  medecin.toml  rh.toml  generic.toml
```

## Tests

### Pyramide

- **Unit (TDD strict)** : `doc_type_classifier`, `doc_metadata_extractor`,
  `audit_v2_migration`, `subject_clustering`, `controller_profile`,
  `dpia_screening` triggers, `processing_register`, `render` (md/docx/pdf).
- **Service-level** (vault SQLite + chunks réels) : `subject_access`,
  `forget_subject_dry_run`, `forget_subject_apply`, `processing_register_e2e`,
  `dpia_e2e`.
- **Privacy invariant tests** (4 dédiés) : aucune raw PII string dans aucun output
  de chaque tool compliance, sauf via `reveal=true` opt-in.

### Test fixtures

`tests/fixtures/compliance/sample_cabinet/` :
- `client1/contract_with_dob.pdf` — declenche DPIA via donnée_naissance
- `client1/medical_note.txt` — donnee_sante (Art. 9)
- `client2/payroll_2026.xlsx` — RH context
- `client2/email_bonjour.eml` — format kreuzberg test
- `client3/acte_notarie.pdf` — header notarial

### "No-PII-leak" tests (privacy invariant)

```python
def test_processing_register_no_raw_pii_in_output():
    """ProcessingRegister never contains raw PII strings."""
    svc = _seeded_service_with_known_pii()
    report = await svc.processing_register("test-project")
    raw_strings = ["Marie Dupont", "marie.dupont@example.com",
                   "FR1420041010050500013M02606"]
    serialized = report.model_dump_json()
    for raw in raw_strings:
        assert raw not in serialized
```

Idem pour `subject_access`, `dpia_screening`, `forget_subject` (tombstone hash, pas
le token brut).

## Risks

| Risque | Impact | Mitigation |
|---|---|---|
| kreuzberg metadata vide pour PDFs scannés non-tagués | doc_date heuristique → moins fiable | `doc_date_source` documenté, l'avocat peut corriger |
| Cluster homonymes mal séparés | Forget excessif | Validation utilisateur obligatoire avant `forget_subject` |
| DPIA-lite faux négatifs sur Art. 35.3.a (profilage manuel) | DPIA non flaggée | Output mentionne triggers manuels à évaluer |
| Templates Jinja2 cassés sur edge cases | PDF malformé | Tests round-trip + sections wrappées dans `{% if %}` |
| Re-embedding coûteux après forget | Minutes de blocage sur gros dossier | Audit event `forget_in_progress` → `forgotten`, async job future |
| `weasyprint` lourd (~80MB) | Install lourd | Optionnel via extra `[compliance]` |
| CNIL met à jour ses lignes directrices DPIA | Triggers obsolètes | Version dans output (`v: 1`), bump si CNIL change |

## Open items (tranchés à l'implémentation)

- **`doc_authors` anonymisation** : si nom déjà connu du vault, stocker placeholder ;
  sinon `anonymize()` avant écriture dans `documents_meta`.
- **`actor` capture** : `os.getlogin()` Phase 0 ; multi-user = sub-projet #5.
- **Concurrence `forget_subject`** : lock per-project en SQLite pendant l'op.
- **Format `doc_date`** : epoch int en stockage, ISO 8601 au render.

## File map

| Path | Type | Phase |
|---|---|---|
| `src/piighost/service/models.py` | modify | 0+1+2 (DocumentMetadata, AuditEvent v2, SubjectCluster, SubjectAccessReport, ForgetReport, ProcessingRegister, DPIAScreening, RenderResult) |
| `src/piighost/service/doc_type_classifier.py` | new | 0 |
| `src/piighost/service/doc_metadata_extractor.py` | new | 0 |
| `src/piighost/service/controller_profile.py` | new | 0 |
| `src/piighost/service/subject_clustering.py` | new | 1 |
| `src/piighost/service/core.py` | modify | 0+1+2 (hooks + 6 méthodes nouvelles) |
| `src/piighost/indexer/ingestor.py` | modify | 0 (extract_with_metadata) |
| `src/piighost/indexer/indexing_store.py` | modify | 0 (documents_meta table + CRUD) |
| `src/piighost/vault/store.py` | modify | 1 (delete_token, docs_containing_tokens, cooccurring_tokens) |
| `src/piighost/vault/audit.py` | modify | 0 (AuditEvent v2 + record_v2) |
| `src/piighost/compliance/__init__.py` | new | 2 |
| `src/piighost/compliance/processing_register.py` | new | 2 |
| `src/piighost/compliance/dpia_screening.py` | new | 2 |
| `src/piighost/compliance/render.py` | new | 2 |
| `src/piighost/compliance/templates/` | new tree | 2 (~6 templates) |
| `src/piighost/compliance/profiles/` | new tree | 0 (~6 fichiers TOML) |
| `src/piighost/mcp/tools.py` | modify | 8 nouveaux ToolSpec |
| `src/piighost/mcp/shim.py` | modify | 8 nouveaux `@mcp.tool` wrappers |
| `src/piighost/daemon/server.py` | modify | 8 dispatch handlers |
| `pyproject.toml` | modify | extras `[compliance]` |
| `.worktrees/hacienda-plugin/skills/setup/SKILL.md` | new | 5 |
| `.worktrees/hacienda-plugin/skills/rgpd-access/SKILL.md` | new | 1 |
| `.worktrees/hacienda-plugin/skills/rgpd-forget/SKILL.md` | new | 1 |
| `.worktrees/hacienda-plugin/skills/rgpd-registre/SKILL.md` | new | 2 |
| `.worktrees/hacienda-plugin/skills/rgpd-dpia/SKILL.md` | new | 2 |
| `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` | modify | bump v0.5.0 |
| `tests/unit/test_doc_type_classifier.py` | new | 0 |
| `tests/unit/test_doc_metadata_extractor.py` | new | 0 |
| `tests/unit/test_audit_v2_migration.py` | new | 0 |
| `tests/unit/test_controller_profile.py` | new | 0 |
| `tests/unit/test_subject_clustering.py` | new | 1 |
| `tests/unit/test_subject_access.py` | new | 1 |
| `tests/unit/test_forget_subject.py` | new | 1 |
| `tests/unit/test_processing_register.py` | new | 2 |
| `tests/unit/test_dpia_screening.py` | new | 2 |
| `tests/unit/test_render.py` | new | 2 |
| `tests/unit/test_no_pii_leak.py` | new | 4 invariant tests, all phases |
| `tests/fixtures/compliance/sample_cabinet/...` | new | shared |

## Effort budget

| Phase | Effort | LOC src | LOC tests |
|---|---|---|---|
| Phase 0 — Foundation | 3 j | ~500 | ~400 |
| Phase 1 — Droits RGPD | 1.5 sem | ~700 | ~550 |
| Phase 2 — Registre + DPIA + Render | 1.5 sem | ~700 | ~500 |
| Section 5 — Wizard | 3 j | ~150 | ~80 |
| **Total** | **~3.5-4 sem** | **~2 050** | **~1 530** |

Single spec, single plan, single PR-cycle attendu.
