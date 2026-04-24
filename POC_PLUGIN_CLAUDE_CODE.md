# POC — Plugin Claude Code « PIIGhost Legal »

> Document de cadrage produit pour un POC rapide combinant `hacienda-ghost` (PIIGhost) et le travail préalable `anonymizer-legal`.
>
> Branche : `claude/analyze-hacienda-ghost-eRPmx`
> Date : 2026-04-24

---

## 1. Synthèse de l'analyse

### 1.1 Comparaison `anonymizer-legal` vs `hacienda-ghost`

`anonymizer-legal` (travail local préalable, Mac, non-git) et `hacienda-ghost` (PIIGhost, repo actuel) ont le même but — anonymiser des PII pour conversations IA — mais avec deux philosophies opposées :

- **`anonymizer-legal`** : plugin Claude Code spécialisé juridique FR, opt-in via commandes `/anon-*`, hooks d'interception (UserPromptSubmit, PreToolUse), 7 profils métier, 5 traitements (MASK / KEEP / GENERALIZE / PSEUDONYM / RELATIVIZE), Presidio + spaCy + Mistral.
- **`hacienda-ghost`** : plateforme générique pour agents IA, middleware LangChain, MCP server, RAG hybride, GLiNER2, vault multi-projet, CLI/daemon. Cible développeurs.

### 1.2 Constat fondamental sur l'interception des requêtes

Vérification du code source de `hacienda-ghost` :

- `src/piighost/integrations/langchain/middleware.py` — `abefore_model` anonymise bien les `HumanMessage`, **mais uniquement dans un agent LangChain construit par un développeur**.
- `plugin/` (PIIGhost) — README l:64 : *« No PreToolUse seatbelt. Cowork plugins don't ship executable hooks (v1). If the user pastes a raw client name into chat, it's up to the skill prose + model discipline to call `anonymize_text` before sending it outbound. »*
- Aucun hook `UserPromptSubmit`, `PreToolUse`, `PostToolUse` dans le repo.

**Conséquence :** dans Claude Desktop / Claude Cowork, PIIGhost **ne peut pas garantir** l'anonymisation des requêtes utilisateur. Il dépend de la « discipline du modèle » — incompatible avec une exigence RGPD/secret professionnel.

### 1.3 Vraies différences (corrigées)

| Différence fondamentale | `anonymizer-legal` | `hacienda-ghost` |
|---|---|---|
| **Interception requêtes user** | ✅ Hook `UserPromptSubmit` → garantie système | ❌ Aucun hook Claude Code, dépend de la discipline du modèle en Desktop/Cowork |
| **Interception fichiers lus** | ✅ Hook `PreToolUse (Read)` → deny + additionalContext anonymisé | ❌ Pas d'équivalent |
| **Interception sortie Bash** | ✅ Hook `PostToolUse` | ❌ Absent |
| **Profils métier juridiques** | ✅ 7 profils × 28 catégories livrés | ❌ 3 presets génériques ; profils verticaux = « paid-support deliverable » (hors repo) |
| **Traitements différenciés** | ✅ 5 (MASK / KEEP / GENERALIZE / PSEUDONYM / RELATIVIZE) | ❌ 4 placeholders techniques (Counter / Hash / Redact / Mask) — pas de vrais pseudonymes ni de généralisation |
| **Dé-anonymisation OFF par défaut** | ✅ RGPD strict | ❌ Désanonymise systématiquement |
| **Legal recognizers FR** | ✅ Articles, jurisprudence | ❌ |
| **Dataset ground truth juridique** | ✅ `tests/fixtures/dataset2/` (PDF, DOCX, XLSX, OCR) | ❌ |

### 1.4 Décision stratégique

**Claude Code est le seul environnement viable** pour une anonymisation fiable des requêtes — il est le seul à offrir des hooks exécutables (`UserPromptSubmit`, `PreToolUse`, etc.) qui interceptent **avant** que le LLM voie le prompt.

> Claude Desktop et Claude Cowork sont écartés du POC tant qu'ils n'ont pas de hooks équivalents.

Architecture cible :

```
┌─────────────────────────────────────────┐
│  Claude Code (CLI / IDE extension)      │
│  ┌───────────────────────────────────┐  │
│  │  Plugin "PIIGhost Legal"          │  │  ← cockpit (issu d'anonymizer-legal)
│  │  - hooks/hooks.json               │  │
│  │  - commands/anon-*.md             │  │
│  │  - skills/                        │  │
│  └────────────┬──────────────────────┘  │
└───────────────┼─────────────────────────┘
                │ stdin/stdout JSON
                ▼
        ┌────────────────────┐
        │  PIIGhost daemon   │  ← moteur (hacienda-ghost)
        │  + pipeline        │
        │  + vault           │
        │  + profils légaux  │  ← à porter depuis anonymizer-legal
        │  + 5 traitements   │  ← à porter
        └────────────────────┘
```

---

## 2. PRD — POC « PIIGhost Legal »

### 2.1 Objectif

Livrer en **2 semaines** un plugin Claude Code installable qui :

1. Intercepte les prompts utilisateur et les anonymise **avant** envoi au LLM.
2. Intercepte les lectures de fichiers (.docx / .pdf / .xlsx) et anonymise leur contenu.
3. Permet d'activer un profil métier juridique via une commande slash (`/anon-deal`, `/anon-litige`, etc.).
4. Désanonymise pour l'affichage utilisateur uniquement (jamais pour le LLM ni pour les outils externes).
5. Tient un audit append-only RGPD.

### 2.2 Cibles utilisateur

- **Avocat** travaillant sur Claude Code, soumis au secret professionnel
- **Cabinet conseil** manipulant des données clients confidentielles
- **DPO interne** vérifiant la conformité RGPD

### 2.3 User stories prioritaires (POC)

| # | User story | Priorité |
|---|---|---|
| US-1 | En tant qu'avocat, je tape `/anon-litige` une fois et toutes mes requêtes suivantes sont anonymisées avant d'arriver au LLM. | 🔴 P0 |
| US-2 | Quand je demande à Claude de lire `dossier_dupont.pdf`, le contenu est extrait et anonymisé avant d'être donné au modèle. | 🔴 P0 |
| US-3 | Quand Claude me répond, je vois les vrais noms (désanonymisés localement), mais le LLM n'a vu que `<<PERSON_1>>`. | 🔴 P0 |
| US-4 | Je peux taper `/anon-status` pour voir le profil actif et le compteur d'entités anonymisées. | 🟠 P1 |
| US-5 | Je peux taper `/anon-off` pour désactiver complètement (mode debug). | 🟠 P1 |
| US-6 | Toute opération est tracée dans un audit append-only signé, consultable via `/anon-audit`. | 🟡 P2 |
| US-7 | Je peux taper `/anon-vault` pour voir les entités anonymisées de la session courante. | 🟡 P2 |

### 2.4 Périmètre

**In scope POC :**
- Plugin Claude Code minimal (hooks + 1 ou 2 commandes)
- 2 profils juridiques (`/anon-litige`, `/anon-deal`) — pas les 7
- 3 traitements sur 5 (MASK, GENERALIZE, PSEUDONYM) — pas KEEP ni RELATIVIZE
- Détection : GLiNER2 (de PIIGhost) + 1 recognizer FR juridique porté
- Formats : `.txt`, `.pdf` texte, `.docx`
- Vault SQLite chiffré (du PIIGhost existant)
- Audit log JSONL append-only

**Out of scope POC (V2+) :**
- Les 5 autres profils métier
- OCR (PDF image, scan)
- Formats `.xlsx`, `.pptx`
- RAG hybride (BM25 + vectoriel)
- Désanonymisation streaming
- Distribution Docker / signing cosign
- Intégration Langfuse / observabilité
- Multi-projet (un seul projet pour le POC)

### 2.5 Architecture POC

```
poc-plugin-claude-code/
├── plugin/
│   ├── hooks/
│   │   └── hooks.json              # UserPromptSubmit + PreToolUse(Read)
│   ├── commands/
│   │   ├── anon-litige.md
│   │   ├── anon-deal.md
│   │   ├── anon-off.md
│   │   └── anon-status.md
│   └── skills/
│       └── pii-protection/SKILL.md
├── scripts/
│   └── pii_gateway.py              # entrée stdin/stdout, appelle daemon
└── (utilise PIIGhost installé via pip/uv)
```

**Flux d'une requête utilisateur :**

```
1. User tape :  "Rédige une mise en demeure pour Jean Dupont"
2. Hook UserPromptSubmit → pii_gateway.py
3. pii_gateway.py → POST daemon /rpc {method:"anonymize", text:"..."}
4. Daemon (PIIGhost) :
   - Pipeline 5 étapes
   - Profil litige actif → traitements MASK pour PERSON
   - Vault stocke mapping <<PERSON_1>> → "Jean Dupont"
   - Retourne "Rédige une mise en demeure pour <<PERSON_1>>"
5. Claude Code envoie au LLM le texte anonymisé
6. LLM répond avec <<PERSON_1>>
7. Hook Stop / affichage → désanonymisation locale
8. User voit "Jean Dupont" dans la réponse, le LLM n'a jamais vu le nom
```

### 2.6 Critères d'acceptation

| # | Critère | Mesure |
|---|---|---|
| AC-1 | Le LLM ne voit jamais un PII en clair quand un profil est actif | Inspection des logs LangFuse / mode debug |
| AC-2 | F1 ≥ 0.85 sur le ground truth `dataset2` (porté depuis anonymizer-legal) | `pytest tests/test_ner_ground_truth.py` |
| AC-3 | Le plugin s'installe en `<5 min` sur un Mac vierge | Test sur machine vierge |
| AC-4 | Latence d'anonymisation ≤ 300ms pour un prompt < 500 tokens | Benchmark `pytest --benchmark` |
| AC-5 | Audit log immuable (append-only, hash chaîné) | Test : modifier une ligne → vérification échoue |
| AC-6 | `/anon-off` puis nouveau prompt → texte brut envoyé au LLM (mode debug) | Test e2e |
| AC-7 | Vault chiffré AES-256-GCM, clé jamais sur disque en clair | Test : `strings vault.db` ne révèle aucun PII |

### 2.7 Plan d'implémentation (10 jours ouvrés)

**Sprint 1 — Socle (J1-J5)**

| Jour | Tâche | Sortie |
|---|---|---|
| J1 | Setup repo POC, fork PIIGhost, branche `poc/legal-claude-code` | Repo en place |
| J2 | Daemon PIIGhost en local + test API `/rpc anonymize` | `curl` retourne texte anonymisé |
| J3 | Plugin minimal : `hooks.json` + `pii_gateway.py` (UserPromptSubmit) | Prompts interceptés, daemon appelé |
| J4 | Hook `PreToolUse(Read)` + extraction `.docx`/`.pdf` (PyMuPDF) | Lecture fichier anonymisée |
| J5 | Désanonymisation pour affichage user (Stop hook ou réécriture inline) | User voit vrais noms, LLM voit tokens |

**Sprint 2 — Métier juridique (J6-J10)**

| Jour | Tâche | Sortie |
|---|---|---|
| J6 | Porter `legal_recognizers_fr.py` depuis anonymizer-legal vers PIIGhost (adapter au protocole `AnyDetector`) | Recognizer FR fonctionnel |
| J7 | Profils `/anon-litige` et `/anon-deal` (chargement YAML/TOML) | Slash commands marchent |
| J8 | Traitements GENERALIZE et PSEUDONYM (étendre `ph_factory`) | Tests unitaires verts |
| J9 | Audit log JSONL append-only + hash chaîné + commande `/anon-audit` | Audit consultable |
| J10 | Démo end-to-end + benchmarks + doc utilisateur 1-page | POC livrable |

### 2.8 Risques & mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| GLiNER2 moins précis que Presidio sur français juridique | Moyenne | Élevé | Benchmark J6 sur ground truth ; fallback Presidio si F1 < 0.8 |
| Hook `UserPromptSubmit` modifie le prompt mais Claude Code l'affiche brut | Faible | Moyen | Tester en J3, replier sur `additionalContext` si besoin |
| Latence cumulée hook + daemon + GLiNER2 > 1s | Moyenne | Moyen | Cache aiocache thread-scoped (déjà dans PIIGhost), warmup au SessionStart |
| Désanonymisation côté affichage user fuite vers logs Claude Code | Élevée | Élevé | Désactiver par défaut en mode RGPD-strict (option opt-in `/anon-reveal`) |
| Plugin Claude Code casse à chaque mise à jour de Claude Code | Moyenne | Moyen | Pin version testée dans plugin manifest, CI multi-versions |

### 2.9 Métriques de succès POC

- ✅ 1 avocat pilote teste 5 cas d'usage réels en moins d'1h sans support
- ✅ 0 fuite de PII vers le LLM sur 100 prompts de test (vérifié dans Langfuse)
- ✅ F1 ≥ 0.85 sur `dataset2` porté
- ✅ Time-to-first-anonymized-response ≤ 2s
- ✅ Demande d'au moins 1 client design-partner pour passer en V1

---

## 3. Prochaines étapes

1. **Validation produit** — Confirmer le périmètre POC avec votre associé
2. **Décision repo** — Travailler sur fork de `hacienda-ghost` ou repo séparé `piighost-legal-plugin` ?
3. **Pilote** — Identifier 1 avocat pour bêta-test fin de POC
4. **Kick-off** — Démarrer Sprint 1 J1

---

## 4. Annexes

### 4.1 Fichiers à porter depuis `anonymizer-legal`

| Source (Mac, local) | Destination (PIIGhost) | Adaptation |
|---|---|---|
| `anonymizer_legal_pii/infrastructure/pii/legal_recognizers_fr.py` | `src/piighost/detector/legal_fr/` | Wrapper protocole `AnyDetector` |
| `anonymizer_legal_pii/infrastructure/profiles/profile_registry.py` | `src/piighost/profiles/` | Adapter au système de presets actuel |
| `tests/fixtures/dataset2/` | `tests/fixtures/legal_fr/` | Tel quel |
| `tests/test_ner_ground_truth.py` | `tests/test_legal_fr_ground_truth.py` | Adapter au pipeline PIIGhost |
| `plugin/hooks/hooks.json` | `plugin/legal/hooks/hooks.json` | Pointer vers daemon PIIGhost |
| `plugin/commands/anon-*.md` | `plugin/legal/commands/` | Tel quel |

### 4.2 Stack technique POC

- **Python ≥3.10**, **uv** (gestionnaire)
- **PIIGhost** (existant) — pipeline, vault, daemon, MCP
- **GLiNER2** — détection NER (déjà dans PIIGhost)
- **PyMuPDF** + **python-docx** — extraction documents
- **portalocker** — locks vault (déjà dans PIIGhost)
- **Claude Code** — runtime du plugin

### 4.3 Décisions ouvertes

- [ ] Repo séparé ou monorepo `hacienda-ghost` ?
- [ ] Modèle économique POC (open-source pur, dual-license, paid-support) ?
- [ ] Profils livrés POC : 2 ou 3 ? (litige + deal, ou ajouter contrat ?)
- [ ] Désanonymisation user-facing : opt-in ou opt-out par défaut ?
- [ ] CI/CD : GitHub Actions sur `jamon8888/hacienda-ghost` ?
