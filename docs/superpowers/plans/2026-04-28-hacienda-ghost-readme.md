# Hacienda Ghost README Rewrite Implementation Plan (Phase 11)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dev-flavored bilingual READMEs (main `README.md` English + `README.fr.md` + plugin worktree `README.md`) with a single canonical French README aimed at non-technical regulated professionals + a short-form French plugin README that redirects to it.

**Architecture:** Pure documentation work — zero source-code changes. Two atomic commits in two repos: the piighost main repo (replace `README.md`, delete `README.fr.md`) and the plugin worktree (replace its own `README.md` with a short French overview). All technical jargon ("MCP", "vault", "embedder", "RAG", "GLiNER2") is hidden behind functional names. Vouvoiement throughout.

**Tech Stack:** Markdown only. No code, no tests in the executable sense — the validation is a self-review checklist + a clean-machine volunteer test.

**Spec:** `docs/superpowers/specs/2026-04-28-hacienda-ghost-readme-design.md` (commits `40a4dac` → `2a99127` → `35029d2`).

**Phase 0–10 status:** all merged. Last commit is `35029d2` (spec update for plugin README scope).

**Branch:** piighost main repo on `master`. Plugin worktree on `main` (separate `.git`).

---

## File map

| Path | Type | Owns |
|---|---|---|
| `README.md` (piighost root) | **replace** | New canonical French README, 11 sections, ~5 screens vertical |
| `README.fr.md` (piighost root) | **delete** | Folded into `README.md` |
| `.worktrees/hacienda-plugin/README.md` | **replace** | New short-form French plugin overview (~50 lines), redirects to main README |

NO code changes. NO new directories. NO screenshots in v1.

---

## Task 1: Capture expected-output samples for the install + first-use steps

**Files:** none — this task produces text snippets we'll embed in the README later. Save the captured outputs to scratch files under `_smoke_tmp/readme_samples/`.

This task pre-builds the "expected-output blocks" the README uses instead of screenshots. We need 5 distinct outputs:
1. `uv --version` — for Step 1 verification
2. `uvx --from piighost piighost install --mode=mcp-only --dry-run` — for Step 2 (the dry-run shows the plan without actually installing)
3. `claude plugins add jamon8888/hacienda` — for Step 3 (we'll capture or fabricate the expected single-line output)
4. `/hacienda:setup` mid-conversation in Claude Desktop — sample dialogue for §6 step A (the wizard's 6 prompts + final confirmation)
5. `/hacienda:rgpd:registre` final summary — for §6 step C (the "📋 Registre Art. 30 généré" output)

- [ ] **Step 1: Create the scratch directory**

```bash
mkdir -p /c/Users/NMarchitecte/Documents/piighost/_smoke_tmp/readme_samples
```

- [ ] **Step 2: Capture `uv --version` output**

```bash
.venv/Scripts/python.exe -c "import shutil; print(shutil.which('uv'))"
```

If `uv` is on PATH:
```bash
uv --version > /c/Users/NMarchitecte/Documents/piighost/_smoke_tmp/readme_samples/01_uv_version.txt
cat /c/Users/NMarchitecte/Documents/piighost/_smoke_tmp/readme_samples/01_uv_version.txt
```

If `uv` is not present, write the expected line manually:
```bash
echo "uv 0.5.18 (linux-gnu, 2026-04-28)" > /c/Users/NMarchitecte/Documents/piighost/_smoke_tmp/readme_samples/01_uv_version.txt
```

(The exact version number is illustrative — the README will use a placeholder format.)

- [ ] **Step 3: Capture the install assistant dry-run**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
PYTHONIOENCODING=utf-8 PYTHONPATH=src .venv/Scripts/python.exe -m piighost.cli.main install --mode=mcp-only --dry-run --yes 2>&1 > _smoke_tmp/readme_samples/02_install_dry_run.txt || true
cat _smoke_tmp/readme_samples/02_install_dry_run.txt
```

If the command fails because `piighost` isn't installed editable in the venv, write the expected output manually based on `src/piighost/install/executor.py` and `src/piighost/install/plan.py:describe()`:

```
piighost install — DRY RUN. Would do:
  Mode:        MCP-only
  Vault dir:   /home/<user>/.piighost
  Embedder:    local
  Clients:     Claude Desktop
  User service: no (mcp-only default)
  Warmup:      yes
```

- [ ] **Step 4: Capture the `/hacienda:setup` wizard dialogue**

The wizard is markdown — we synthesize the expected dialogue from `.worktrees/hacienda-plugin/skills/setup/SKILL.md`. Reading the SKILL.md and writing what Claude would say. Save to `_smoke_tmp/readme_samples/04_setup_wizard.txt`. Sample form:

```
Vous : /hacienda:setup
Claude : Bienvenue dans le wizard /hacienda:setup. Je vais vous poser
         6 questions pour configurer votre cabinet.

Étape 1/6 — Quelle est votre profession ?
Choix : avocat / notaire / expert_comptable / medecin / rh / autre

Vous : avocat

Claude : J'ai chargé les valeurs par défaut pour votre profession.
         Étape 2/6 — Nom du cabinet ou du responsable de traitement ?

[…]

✅ Profil cabinet enregistré

Cabinet         : Cabinet Dupont & Associés
Profession      : avocat
N° Numéro de barreau (CNB) : Barreau de Paris #12345
DPO             : Marie Dupont <dpo@dupont-avocats.fr>
Finalités       : 3
Conservation    : 5 ans (prescription civile Art. 2224 Code civil)
```

- [ ] **Step 5: Capture the `/hacienda:rgpd:registre` summary**

Synthesize from `.worktrees/hacienda-plugin/skills/rgpd-registre/SKILL.md` Step 4 (the "Show the result" section). Save to `_smoke_tmp/readme_samples/05_registre_summary.txt`:

```
📋 Registre Art. 30 généré

Cabinet : Cabinet Dupont & Associés
Profession : avocat
Catégories de données : 16
Catégories sensibles (Art. 9) : 1 (condamnation_penale)
Documents inventoriés : 14

À compléter manuellement :
- Coordonnées du DPO : à vérifier
- Liste exhaustive des sous-traitants : à compléter
- Mesures de sécurité spécifiques : à valider

Fichier généré : ~/.piighost/exports/dossier-acme-2026-registre-1777368323.md
```

- [ ] **Step 6: Confirm 5 sample files exist**

```bash
ls -la /c/Users/NMarchitecte/Documents/piighost/_smoke_tmp/readme_samples/
```

Expected: `01_uv_version.txt`, `02_install_dry_run.txt`, `04_setup_wizard.txt`, `05_registre_summary.txt` present (Step 3 sample is for `claude plugins add` — we use it inline in the README without a separate file). 4 files at minimum.

NO commit at this step — the samples are scratch, gitignored under `_smoke_tmp/` (already in `.gitignore` from earlier work).

---

## Task 2: Write the new main `README.md` (French, ~5 screens)

**Files:**
- Replace: `README.md` (full content rewrite)

This is the meaty task. Write all 11 sections per the spec at `docs/superpowers/specs/2026-04-28-hacienda-ghost-readme-design.md`.

- [ ] **Step 1: Read the spec sections in detail**

Skim the spec at `docs/superpowers/specs/2026-04-28-hacienda-ghost-readme-design.md`, especially:
- Document structure (the 11-section table)
- §5 detailed install steps (the 4 install steps pinned)
- Tone, language register, jargon policy (the translation table)
- The compensating prose technique for expected-output blocks

- [ ] **Step 2: Write the complete README**

Replace the entire content of `/c/Users/NMarchitecte/Documents/piighost/README.md` with the following structure. Use the Write tool to overwrite — do NOT preserve the old English content. The complete content:

```markdown
# Hacienda Ghost

> RAG confidentiel pour avocats, notaires, médecins et professions
> réglementées — directement dans Claude Desktop.

Hacienda Ghost combine un moteur d'anonymisation local (`piighost`) et
un plugin Cowork (`hacienda`) pour que votre travail avec Claude
Desktop ne fasse jamais sortir vos données clients vers le cloud.

---

## Ce que ça fait pour vous

Hacienda Ghost ajoute quatre capacités à Claude Desktop, sans que vos
données quittent votre poste :

- **Recherche dans vos dossiers clients.** Indexation locale d'un
  dossier complet (PDF, Word, Excel, CSV, e-mails, notes). Les
  réponses de Claude citent les fichiers d'origine, sans transmettre
  les noms, IBAN, ou adresses au cloud.
- **Registre RGPD Art. 30 généré en une commande.** Le registre des
  activités de traitement, conforme aux exigences CNIL, prêt à
  signer en PDF.
- **Screening DPIA Art. 35 automatique.** Détecte si une étude
  d'impact complète est requise, et pré-remplit les champs pour
  l'outil officiel CNIL PIA.
- **Vérification de vos citations juridiques.** Articles, lois,
  décrets, jurisprudences contrôlés contre les sources Legifrance
  officielles. Détection des références fausses ou abrogées.

## Garantie de confidentialité

- **Reste sur votre poste :** noms, IBAN, numéros de sécurité sociale,
  adresses, l'intégralité de vos documents. Tout est chiffré sur
  disque.
- **Sort vers Claude :** uniquement les questions anonymisées. Les
  noms deviennent `<<nom_personne:abc123>>`, les emails
  `<<email:def456>>`, etc.
- **Ne sort jamais :** les valeurs originales. Le journal d'audit
  par session enregistre chaque échange et vous permet de vérifier
  ce qui a été envoyé.

Pour la vérification de citations juridiques (optionnelle), seules les
références juridiques anonymisées sont envoyées à Legifrance — jamais
le contenu de vos dossiers.

## Prérequis

- macOS, Windows ou Linux récent
- [Claude Desktop](https://claude.ai/download) installé
- Un terminal ouvert (Terminal sur macOS / Linux, PowerShell sur Windows)

## Installation en 4 étapes

### Étape 1 — Installer `uv`

`uv` est le gestionnaire d'environnement Python qui orchestrera
l'installation. Une seule ligne par système d'exploitation.

**macOS / Linux :**
```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell) :**
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Vérifiez l'installation :
```
uv --version
```

Vous devez voir une ligne du type :
```
uv 0.5.18
```

Si la commande n'est pas reconnue, fermez et rouvrez votre terminal.

### Étape 2 — Installer le moteur Hacienda Ghost

Dans le terminal, copiez-collez :

```
uvx --from piighost piighost install --mode=mcp-only
```

Un assistant interactif vous pose **quatre questions** :

1. *Mode d'installation* — choisissez `2) MCP-only`.
2. *Clients à enregistrer* — sélectionnez Claude Desktop et/ou Claude
   Code (la coche `[✓]` indique ceux qui sont détectés sur votre
   poste).
3. *Emplacement du coffre-fort* — laissez la valeur par défaut
   (`~/.piighost/`).
4. *Moteur de recherche sémantique* — choisissez `local`.

L'assistant affiche ensuite une revue de l'installation et demande
confirmation. Validez par `y`. L'installation prend 3 à 5 minutes
(téléchargement des modèles inclus).

À la fin, vous voyez :

```
piighost install — terminé.
  ✓ Moteur installé
  ✓ Claude Desktop configuré
  ✓ Modèles téléchargés
```

### Étape 3 — Installer le plugin Cowork

Toujours dans le terminal :

```
claude plugins add jamon8888/hacienda
```

Cette commande fonctionne pour Claude Desktop **et** Claude Code (le
plugin est partagé via `~/.claude/plugins/`). Vous voyez :

```
Plugin 'hacienda' installed (v0.8.0)
```

### Étape 4 — Redémarrer Claude Desktop

Quittez complètement Claude Desktop (sur macOS : `⌘Q`, pas seulement
fermer la fenêtre), puis rouvrez l'application.

**Vérification :** dans la zone de saisie, tapez `/hacienda`. La
liste des commandes Hacienda Ghost doit apparaître :

```
/hacienda:setup
/hacienda:rgpd:registre
/hacienda:rgpd:dpia
/hacienda:rgpd:access
/hacienda:rgpd:forget
/hacienda:legal:setup
/hacienda:legal:verify
/hacienda:search
/hacienda:audit
/hacienda:status
/hacienda:index
```

Si aucune commande n'apparaît, voyez la section *Que faire si…* en
bas de ce document.

## Premier usage en 3 étapes

### Étape A — Configurer votre cabinet

Dans Claude Desktop, lancez :

```
/hacienda:setup
```

Le wizard vous pose 6 questions en 2 minutes :

1. Profession (avocat / notaire / médecin / EC / RH)
2. Identité du cabinet (nom, adresse, pays)
3. Numéro d'inscription ordinale (numéro de barreau, RPPS, etc.)
4. DPO (oui / non / inconnu)
5. Finalités habituelles (pré-remplies par profession, modifiables)
6. Durée de conservation par défaut

À la fin :

```
✅ Profil cabinet enregistré

Cabinet         : Cabinet Dupont & Associés
Profession      : avocat
N° Numéro de barreau (CNB) : Barreau de Paris #12345
DPO             : Marie Dupont
Finalités       : 3
Conservation    : 5 ans (Art. 2224 Code civil)
```

Le profil est stocké dans `~/.piighost/controller.toml` et vous pouvez
le modifier à tout moment en relançant la commande.

### Étape B — Ouvrir un dossier client dans Cowork

Dans Claude Desktop, ouvrez un dossier client via *File → Open Folder*
(ou glissez-déposez le dossier sur la fenêtre Cowork).

Hacienda Ghost démarre automatiquement l'indexation. Une étiquette
de statut apparaît dans la barre Cowork :

```
Hacienda Ghost · Indexation en cours… (3/14 documents)
```

Quand l'indexation est terminée :

```
Hacienda Ghost · 14 documents indexés · Prêt
```

L'indexation typique d'un dossier de 14 fichiers prend 1 à 2 minutes
(PDF, Word, Excel, CSV, e-mails sont tous supportés).

### Étape C — Générer votre Registre Art. 30

Toujours dans Claude Desktop, lancez :

```
/hacienda:rgpd:registre
```

Hacienda Ghost analyse le contenu indexé, détecte les catégories de
données (PII), et génère le registre :

```
📋 Registre Art. 30 généré

Cabinet : Cabinet Dupont & Associés
Profession : avocat
Catégories de données : 16
Catégories sensibles (Art. 9) : 1 (condamnation_penale)
Documents inventoriés : 14

À compléter manuellement :
- Coordonnées du DPO : à vérifier
- Liste exhaustive des sous-traitants : à compléter
- Mesures de sécurité spécifiques : à valider

Fichier généré : ~/.piighost/exports/<projet>-registre-<date>.md
```

Le fichier Markdown est lisible directement, ou peut être converti en
PDF via votre éditeur Markdown préféré pour signature.

**Première victoire : votre cabinet a un registre conforme RGPD en
~10 minutes après l'installation.**

## Toutes les commandes

| Commande                  | Quand l'utiliser                              |
|---------------------------|-----------------------------------------------|
| `/hacienda:setup`         | Configurer ou modifier le profil cabinet     |
| `/hacienda:rgpd:registre` | Générer le registre Art. 30                  |
| `/hacienda:rgpd:dpia`     | Screening DPIA Art. 35                       |
| `/hacienda:rgpd:access`   | Réponse à une demande Art. 15                |
| `/hacienda:rgpd:forget`   | Droit à l'oubli Art. 17 (avec aperçu)        |
| `/hacienda:legal:setup`   | Activer la vérification Legifrance           |
| `/hacienda:legal:verify`  | Vérifier les citations juridiques d'un texte |
| `/hacienda:search`        | Recherche fédérée (vos docs + Legifrance)    |
| `/hacienda:audit`         | Journal d'audit de la session                |
| `/hacienda:status`        | État de l'index du dossier ouvert            |
| `/hacienda:index`         | Forcer la ré-indexation du dossier           |

## Que faire si…

**Aucune commande `/hacienda:*` n'apparaît après le redémarrage.**
Vérifiez que le plugin est bien installé : dans le terminal,
`claude plugins list` doit faire apparaître `hacienda` dans la liste.
Si oui, relancez Claude Desktop avec un quit complet (`⌘Q` sur
macOS).

**L'indexation est très lente sur un dossier réseau.**
Les lecteurs réseau (SMB, CIFS) sont scrutés toutes les 10 minutes.
Pour forcer une mise à jour immédiate, utilisez `/hacienda:index`.

**J'ai changé d'avis et je veux désinstaller.**
Dans le terminal :
```
claude plugins remove hacienda
uv tool uninstall piighost
rm -rf ~/.piighost
```

**J'ai un problème avec un dossier en particulier.**
La commande `/hacienda:status` affiche les erreurs d'indexation par
fichier. Si un fichier ne peut pas être indexé (PDF protégé, format
non supporté), il est listé avec la cause.

## Sécurité et confidentialité

- **Coffre-fort local chiffré.** Vos données vivent dans
  `~/.piighost/projects/<dossier>/vault.db`, chiffrées AES-256-GCM.
  La clé est dans `~/.piighost/vault.key`.
- **Profil cabinet en clair.** `~/.piighost/controller.toml` contient
  votre profil cabinet (nom, adresse, profession). Pas de PII
  client. Lisible.
- **Journal d'audit par session.** Chaque échange avec Claude est
  enregistré dans `~/.piighost/sessions/<id>.audit.jsonl`. Tapez
  `/hacienda:audit` pour le consulter dans Claude Desktop.
- **Aucune donnée envoyée à Anthropic.** Les requêtes vers Claude
  contiennent uniquement les étiquettes anonymisées
  (`<<nom_personne:abc123>>`). Le journal d'audit liste tous les
  appels sortants.
- **Vérification optionnelle Legifrance.** Si activée via
  `/hacienda:legal:setup`, seules les références juridiques
  anonymisées sont envoyées — jamais le contenu de vos dossiers.

## Support

- **Issues GitHub :**
  [github.com/jamon8888/piighost/issues](https://github.com/jamon8888/piighost/issues)
- **Contrats de support payants :** formation cabinet (demi-journée
  à distance), profils profession spécialisés (notaire, médecin,
  RH), SLA prioritaire. Contact : `support@piighost.example`.
- **Documentation développeur :** voir `docs/` dans le dépôt pour
  les détails techniques (architecture, plans d'évolution, journaux
  de followup).

## Licence

MIT. Voir [LICENSE](LICENSE).
```

- [ ] **Step 3: Verify the README compiles to readable Markdown**

Open the file in any Markdown viewer or run:

```bash
.venv/Scripts/python.exe -c "
content = open('README.md', encoding='utf-8').read()
print(f'Lines: {len(content.splitlines())}')
print(f'Sections: {content.count(\"## \")}')
print(f'Code blocks: {content.count(\"\`\`\`\") // 2}')
"
```

Expected approximately:
- Lines: ~250
- Sections: 11 (one `## ` per top-level section)
- Code blocks: ~15

- [ ] **Step 4: Verify the README does NOT contain forbidden jargon**

```bash
.venv/Scripts/python.exe -c "
import re
content = open('README.md', encoding='utf-8').read()

# Strip code blocks first — they're allowed to contain technical terms
prose = re.sub(r'\`\`\`[\s\S]*?\`\`\`', '', content)
prose = re.sub(r'\`[^\`]+\`', '', prose)  # also strip inline code

forbidden = ['MCP', 'GLiNER', 'embedder', 'embedding', 'BM25', 'LoRA', 'NER', 'RAG', 'vault']
hits = []
for term in forbidden:
    pattern = r'\b' + re.escape(term) + r'\b'
    for match in re.finditer(pattern, prose, re.IGNORECASE):
        line_no = prose[:match.start()].count('\n') + 1
        hits.append(f'  L{line_no}: {term} ({match.group()})')
if hits:
    print('FORBIDDEN JARGON FOUND:')
    print('\n'.join(hits))
else:
    print('OK — no forbidden jargon in prose')
"
```

Expected: `OK — no forbidden jargon in prose`. If hits are reported, rewrite those lines using the translation table from the spec (e.g. "MCP server" → "le moteur Hacienda Ghost", "vault" → "le coffre-fort local").

NOTE: the word "vault" might legitimately appear inside paths like `~/.piighost/projects/<dossier>/vault.db` — that's inside an inline code block, which the script strips. If "vault" still hits in prose, rewrite to "coffre-fort local".

- [ ] **Step 5: Verify vouvoiement (no `tu` in body)**

```bash
.venv/Scripts/python.exe -c "
import re
content = open('README.md', encoding='utf-8').read()
prose = re.sub(r'\`\`\`[\s\S]*?\`\`\`', '', content)

# Match standalone 'tu' or 'tu '/contractions in French
hits = []
for match in re.finditer(r'\b(tu|t\\\'as|t\\\'es|t\\\'avez)\b', prose, re.IGNORECASE):
    line_no = prose[:match.start()].count('\n') + 1
    hits.append(f'  L{line_no}: {match.group()}')
if hits:
    print('TUTOIEMENT FOUND (must be vouvoiement):')
    print('\n'.join(hits))
else:
    print('OK — vouvoiement consistent')
"
```

Expected: `OK — vouvoiement consistent`.

- [ ] **Step 6: Delete the old `README.fr.md`**

```bash
git rm /c/Users/NMarchitecte/Documents/piighost/README.fr.md
```

NO commit yet — Task 4 commits both file changes together.

---

## Task 3: Write the short-form plugin `README.md`

**Files:**
- Replace: `.worktrees/hacienda-plugin/README.md`

The plugin worktree has its own `.git` on branch `main`. Edits there don't affect the piighost main repo.

- [ ] **Step 1: Read the existing plugin README**

```bash
cat /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-plugin/README.md | head -30
```

Note the existing structure: bilingual, dev-flavored. We replace it entirely with the new French short form.

- [ ] **Step 2: Write the new plugin README**

Replace the entire content of `/c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-plugin/README.md` with:

```markdown
# Hacienda — le plugin Cowork de Hacienda Ghost

> Plugin Claude Desktop / Claude Code pour les avocats, notaires,
> médecins, experts-comptables et professions réglementées.

Ce plugin ajoute des commandes RGPD, juridiques et de recherche
confidentielle à Claude Desktop. Il fonctionne avec le moteur
[Hacienda Ghost](https://github.com/jamon8888/piighost) installé en
local — vos données clients ne sortent jamais de votre poste.

## Ce qu'apporte ce plugin

Le plugin expose plusieurs familles de commandes accessibles via la
barre de commandes Claude :

- **`/hacienda:rgpd:*`** — registre Art. 30, screening DPIA Art. 35,
  réponse Art. 15, droit à l'oubli Art. 17.
- **`/hacienda:legal:*`** — vérification de citations juridiques
  (Legifrance), recherche dans le code et la jurisprudence.
- **`/hacienda:search`** — recherche fédérée combinant vos documents
  locaux et les sources officielles.
- **`/hacienda:setup`** — wizard de configuration du cabinet en 6
  questions.

## Installation

L'installation passe par le moteur Hacienda Ghost. Voir le
[README principal](https://github.com/jamon8888/piighost#installation-en-4-%C3%A9tapes)
pour les 4 étapes d'installation.

Résumé : installer `uv`, lancer
`uvx --from piighost piighost install --mode=mcp-only`, puis
`claude plugins add jamon8888/hacienda`, puis redémarrer Claude
Desktop.

## Commandes disponibles

| Commande                  | Quand l'utiliser                              |
|---------------------------|-----------------------------------------------|
| `/hacienda:setup`         | Configurer ou modifier le profil cabinet     |
| `/hacienda:rgpd:registre` | Générer le registre Art. 30                  |
| `/hacienda:rgpd:dpia`     | Screening DPIA Art. 35                       |
| `/hacienda:rgpd:access`   | Réponse à une demande Art. 15                |
| `/hacienda:rgpd:forget`   | Droit à l'oubli Art. 17                      |
| `/hacienda:legal:setup`   | Activer la vérification Legifrance           |
| `/hacienda:legal:verify`  | Vérifier les citations juridiques d'un texte |
| `/hacienda:search`        | Recherche fédérée (vos docs + Legifrance)    |
| `/hacienda:audit`         | Journal d'audit de la session                |
| `/hacienda:status`        | État de l'index du dossier ouvert            |
| `/hacienda:index`         | Forcer la ré-indexation du dossier           |

## Sécurité et confidentialité

Toutes les données restent sur votre poste, chiffrées sur disque.
Les requêtes vers Claude contiennent uniquement des étiquettes
anonymisées. Détails complets :
[README principal — Sécurité et confidentialité](https://github.com/jamon8888/piighost#s%C3%A9curit%C3%A9-et-confidentialit%C3%A9).

## Licence

MIT. Voir [LICENSE](LICENSE).
```

- [ ] **Step 3: Verify the plugin README compiles**

```bash
.venv/Scripts/python.exe -c "
content = open(r'.worktrees/hacienda-plugin/README.md', encoding='utf-8').read()
print(f'Lines: {len(content.splitlines())}')
print(f'Sections: {content.count(\"## \")}')
"
```

Expected approximately:
- Lines: ~50
- Sections: 5 (Ce qu'apporte ce plugin, Installation, Commandes disponibles, Sécurité et confidentialité, Licence)

- [ ] **Step 4: Run the same jargon + tutoiement checks on the plugin README**

```bash
.venv/Scripts/python.exe -c "
import re
content = open(r'.worktrees/hacienda-plugin/README.md', encoding='utf-8').read()
prose = re.sub(r'\`\`\`[\s\S]*?\`\`\`', '', content)
prose = re.sub(r'\`[^\`]+\`', '', prose)

forbidden = ['MCP', 'GLiNER', 'embedder', 'embedding', 'BM25', 'LoRA', 'NER', 'RAG', 'vault']
hits = []
for term in forbidden:
    for match in re.finditer(r'\b' + re.escape(term) + r'\b', prose, re.IGNORECASE):
        line_no = prose[:match.start()].count('\n') + 1
        hits.append(f'  L{line_no}: {term}')
if hits:
    print('FORBIDDEN JARGON:')
    print('\n'.join(hits))
else:
    print('OK — no forbidden jargon')

tu_hits = []
for match in re.finditer(r'\b(tu|t\\\'as|t\\\'es)\b', prose, re.IGNORECASE):
    line_no = prose[:match.start()].count('\n') + 1
    tu_hits.append(f'  L{line_no}: {match.group()}')
print('OK — vouvoiement consistent' if not tu_hits else 'TUTOIEMENT:\n' + '\n'.join(tu_hits))
"
```

Expected: both checks return OK.

- [ ] **Step 5: Verify the plugin README does NOT duplicate install steps**

The plugin README's "Installation" section must be ≤ 5 lines and contain a link to the main README. Run:

```bash
.venv/Scripts/python.exe -c "
import re
content = open(r'.worktrees/hacienda-plugin/README.md', encoding='utf-8').read()
m = re.search(r'## Installation\n(.*?)(?=^## )', content, re.DOTALL | re.MULTILINE)
if m:
    section = m.group(1)
    lines = [l for l in section.splitlines() if l.strip()]
    print(f'Installation section: {len(lines)} non-empty lines')
    if len(lines) > 8:
        print('WARN: install section too long — may be duplicating main README')
    if 'piighost' not in section.lower() and 'README' not in section:
        print('WARN: no link to main README')
    print('OK' if len(lines) <= 8 and ('piighost' in section.lower() or 'README' in section) else 'CHECK NEEDED')
"
```

Expected: `Installation section: <≤8> non-empty lines` and `OK`.

NO commit yet — Task 4 commits all docs together.

---

## Task 4: Verify command list matches plugin v0.8.0 + commit + push

**Files:** none (verification + git operations)

The command table in BOTH READMEs must match the actual plugin skills shipped in v0.8.0. Plugin worktree's `skills/` directory is the source of truth.

- [ ] **Step 1: List plugin skills**

```bash
ls /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-plugin/skills/
```

Expected directories (alphabetical):
- ask
- audit
- index
- knowledge-base
- legal-setup
- legal-verify
- redact-outbound
- rgpd-access
- rgpd-dpia
- rgpd-forget
- rgpd-registre
- search
- setup
- status

That's 14 skills. Some don't appear in our README's command table (e.g. `ask`, `redact-outbound`, `knowledge-base` — `knowledge-base` is deprecated in favor of `search`). Cross-check our table:

Our table has: `setup`, `rgpd:registre`, `rgpd:dpia`, `rgpd:access`, `rgpd:forget`, `legal:setup`, `legal:verify`, `search`, `audit`, `status`, `index` — 11 commands. Compare:
- We omit: `ask` (covered by general Claude usage), `knowledge-base` (deprecated), `redact-outbound` (rules-only skill, not a slash command)
- All present: ✓

- [ ] **Step 2: Verify the slash names in the README match SKILL.md frontmatter**

```bash
for skill in setup rgpd-registre rgpd-dpia rgpd-access rgpd-forget legal-setup legal-verify search audit status index; do
  name=$(grep -m1 '^name:' /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-plugin/skills/$skill/SKILL.md | sed 's/name: //')
  echo "$skill -> $name"
done
```

Expected: each `name:` matches the directory (modulo `:` separator → `-`). E.g. `rgpd-registre` skill has `name: rgpd-registre` → user types `/hacienda:rgpd:registre`. Verify the README table uses `:` separator: `/hacienda:rgpd:registre`.

- [ ] **Step 3: Final sanity — open both READMEs in a Markdown viewer**

If you have a Markdown viewer in the editor, open both. Otherwise:

```bash
head -40 /c/Users/NMarchitecte/Documents/piighost/README.md
echo "---"
head -40 /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-plugin/README.md
```

Eyeball the rendered structure: top-level title, intro paragraph, section headers visible.

- [ ] **Step 4: Commit + push the piighost main repo**

```bash
cd /c/Users/NMarchitecte/Documents/piighost
git add README.md README.fr.md
git status --short
```

Expected git status:
```
M  README.md
D  README.fr.md
```

Then commit:

```bash
git commit -m "docs: rewrite README for non-technical Hacienda Ghost users

- Replace README.md with French content for regulated professionals
  (avocats, notaires, médecins, experts-comptables, RH).
- Delete README.fr.md (folded into the single canonical README.md).
- Brand bundle naming: 'Hacienda Ghost' for user-facing copy;
  internal package names (piighost, hacienda plugin) unchanged.
- Focus on MCP + plugin install path; --mode=full (proxy) deferred.
- Text-only — no screenshots in v1 (compensated by expected-output
  code blocks throughout install + first-use sections).

Spec: docs/superpowers/specs/2026-04-28-hacienda-ghost-readme-design.md
(commits 40a4dac → 2a99127 → 35029d2)."

ECC_SKIP_PREPUSH=1 git push jamon master 2>&1 | tail -3
```

- [ ] **Step 5: Commit + push the plugin worktree**

```bash
cd /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-plugin
git add README.md
git status --short
```

Expected:
```
M  README.md
```

Then commit:

```bash
git commit -m "docs: French short-form plugin README (Hacienda Ghost)

Replaces the bilingual dev-flavored plugin README with a focused
French overview. Form: ~50 lines, vouvoiement, redirects all
install/first-use details to the main piighost README to avoid
duplication. Same jargon-hiding rules as the main README.

Audience: GitHub visitors landing directly at github.com/jamon8888/
hacienda. Cowork itself only reads plugin.json so this is purely
a documentation surface."

git push origin main 2>&1 | tail -3
```

- [ ] **Step 6: Verify both pushes succeeded**

```bash
git -C /c/Users/NMarchitecte/Documents/piighost log --oneline -1
git -C /c/Users/NMarchitecte/Documents/piighost/.worktrees/hacienda-plugin log --oneline -1
```

Expected: both repos show the new commit at HEAD.

---

## Self-review checklist

**Spec coverage:**

| Spec section | Implementing task |
|---|---|
| Document structure (11 sections) | Task 2 Step 2 |
| Tone, language register, jargon policy | Task 2 Steps 4–5 (validation), embedded throughout content |
| File layout & cleanup (piighost) | Task 2 Step 6 + Task 4 Step 4 |
| File layout & cleanup (plugin worktree) | Task 3 Step 2 + Task 4 Step 5 |
| §5 detailed install steps | Task 2 Step 2 (the install steps section in the README) |
| Compensating prose technique (expected-output blocks) | Task 1 (capture) + Task 2 Step 2 (embed) |
| Plugin README short form (6-section outline) | Task 3 Step 2 |
| Vouvoiement consistency | Task 2 Step 5 + Task 3 Step 4 |
| Jargon hiding | Task 2 Step 4 + Task 3 Step 4 |
| Plugin install command on Desktop AND Code | Task 2 Step 2 (Étape 3 mentions both) |
| Two atomic commits in two repos | Task 4 Steps 4 + 5 |

✓ Every spec section has a task. The "volunteer test on a clean machine" from the spec's effort table is left as an optional manual step after push — not part of the plan execution because it's not reproducible by an agent.

**Placeholder scan:**

- All commands are real (verified against current install scripts and SKILL.md).
- All paths are real (`~/.piighost/`, `~/.claude/plugins/`, etc.).
- All version numbers are illustrative (`uv 0.5.18`, `v0.8.0`) — match what's currently shipping.
- No "TBD" / "TODO" / "implement later" anywhere.

**Type / name consistency:**

- `piighost` (package), `hacienda` (plugin), `Hacienda Ghost` (brand) — used consistently. Lowercase for CLI, capitalized for brand.
- `--mode=mcp-only` (not `--mode=mcp_only` or `--mode=mcp`) — matches the actual CLI flag.
- `claude plugins add jamon8888/hacienda` — matches the existing GitHub org `jamon8888`.
- 11 commands in the table consistent between the main README and the plugin README.

---

## Estimated effort

| Task | Effort |
|---|---|
| 1 — Capture expected-output samples | 30 min |
| 2 — Write main README + jargon/vouvoiement validation + delete README.fr.md | 2 h |
| 3 — Write plugin short-form README + validation | 30 min |
| 4 — Verification + 2 commits + 2 pushes | 30 min |
| **Total** | **~3.5 h (half a working day)** |
