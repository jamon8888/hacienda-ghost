# Hacienda Ghost README — Design Spec

**Date:** 2026-04-28
**Phase target:** Phase 11 (documentation rewrite for non-technical users)
**Status:** Design approved, ready for implementation plan

This document specifies the rewrite of the piighost project's user-facing README. The new README replaces both `README.md` (English, dev-flavored) and `README.fr.md` (French, dev-flavored) with a single French README aimed at non-technical regulated professionals (avocats, notaires, médecins, experts-comptables, RH/DPO). Brand: **Hacienda Ghost** — the bundle of piighost (engine) + hacienda (Cowork plugin).

---

## Goals

1. **Non-technical install path.** A French-speaking avocat can go from "I clicked a GitHub link" to "I have my Art. 30 register generated" in ~10 minutes, with two terminal commands they paste verbatim. No prior Python knowledge, no developer terminology.
2. **Brand bundling.** Surface "Hacienda Ghost" as the consumer-facing product name. Internal command names (`piighost install`, `claude plugins add jamon8888/hacienda`) stay unchanged — no PyPI/repo rename.
3. **Privacy guarantee made visible.** A regulated professional reading the README must understand within the first screen what stays local, what leaves the machine, and what never leaves. This is the buying decision.
4. **First-use win demonstrated.** Reader walks away with a working install AND a tangible compliance artefact (the Art. 30 register PDF). Closing this loop in the README itself converts trial users into adopters.

## Non-goals

- A marketing landing page (separate concern; lives on a future hacienda-ghost.fr site, not in the README).
- An English README. Audience is French-speaking; PyPI's auto-translation handles non-French dev visitors.
- Coverage of the proxy install mode. Deferred — the README explicitly omits `--mode=full` and the ANTHROPIC_BASE_URL hijacking story.
- Developer/contributor documentation. Separate `CONTRIBUTING.md` or `docs/dev.md` is out of scope.
- Visuals of any kind. v1 is text-only — no GIFs, no screenshots, no diagrams. Captured imagery drifts on every minor release and adds maintenance cost; the prose is responsible for being clear without leaning on screenshots.

---

## Audience

**Primary:** French regulated professional, comfortable with email and Word, has installed Claude Desktop, has never run a Python tool. Will paste two commands the README provides verbatim. Will not edit JSON config files. Will not read past the install section if the install fails.

**Reading device:** desktop browser on github.com or a hosted page. Not phone, not e-reader.

**Reading mode:** "scan first, read what matters, paste commands". The README must look skimmable — short paragraphs, bullets, code blocks set off clearly.

---

## Document structure (locked)

11 sections, ~5 screens of vertical scroll, text-only:

| § | Title | Length | Includes |
|---|---|---|---|
| 1 | Hacienda Ghost en bref | ~3 lines | One-sentence hook + 1-line context |
| 2 | Ce que ça fait pour vous | ~10 lines | 4 capability bullets |
| 3 | Garantie de confidentialité | ~5 lines | What stays local / what goes outbound / what never leaves |
| 4 | Prérequis | 3 bullets | OS, Claude Desktop, terminal access |
| 5 | Installation en 4 étapes | ~30 lines | Numbered steps, paste-and-go, expected output samples |
| 6 | Premier usage en 3 étapes | ~30 lines | Wizard → indexing → registre — described in prose with sample dialogue snippets |
| 7 | Toutes les commandes | 1 table (~12 rows) | Slash commands quick reference |
| 8 | Que faire si… | ~20 lines | 4 troubleshooting Q&As |
| 9 | Sécurité et confidentialité | ~10 lines | File locations, encryption, audit log |
| 10 | Support | ~5 lines | GitHub issues, paid contracts |
| 11 | Licence | 1 line | MIT |

The full outline detail (with sample prose for §2 and §5.2) is in Brainstorming Section 1.

**Compensating prose technique.** Without screenshots, the install and first-use sections rely on **expected-output blocks** — code blocks that show what the user should see in their terminal or in Claude's reply, so they can confirm visually that they're on track. Sample form for §5 step 2:

```
[piighost install] Vérification de l'environnement…
[piighost install] ✓ Python 3.13 détecté
[piighost install] ✓ Espace disque suffisant (12.4 GB libres)
[piighost install] ✓ Connexion internet
[piighost install] Téléchargement des modèles… (3-5 min)
```

The prose then says: *"Lorsque vous voyez la dernière ligne, le moteur est prêt."*

### §5 — Detailed install steps

The 4 install steps in §5 are pinned here so the README writer doesn't have to re-litigate ordering decisions:

**Étape 1 — Installer `uv` (gestionnaire Python).**
- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- Vérification: `uv --version` doit afficher un numéro de version.

**Étape 2 — Installer le moteur Hacienda Ghost.**
- Commande unique: `uvx --from piighost piighost install --mode=mcp-only`
- Assistant interactif: 4 prompts (mode / clients à enregistrer / coffre-fort / moteur de recherche sémantique).
- L'assistant détecte automatiquement Claude Desktop ET Claude Code s'ils sont présents et propose de les enregistrer tous les deux. Le lecteur peut choisir l'un ou l'autre, ou les deux.
- Durée: 3 à 5 minutes (téléchargement des modèles inclus).

**Étape 3 — Installer le plugin Cowork (Hacienda).**
- Pour Claude Desktop: `claude plugins add jamon8888/hacienda`
- Pour Claude Code: la même commande fonctionne (Cowork est partagé entre Desktop et Code via `~/.claude/plugins/`).
- Vérification: la commande affiche `Plugin 'hacienda' installed (v0.8.0)`.
- Le README mentionne explicitement les deux cibles ("dans Claude Desktop *et/ou* dans Claude Code") — l'auto-détection à l'étape 2 a déjà câblé le moteur dans les deux ; cette étape ajoute les commandes `/hacienda:*` à la palette.

**Étape 4 — Redémarrer Claude Desktop (ou Claude Code).**
- Quitter complètement (pas seulement fermer la fenêtre — sur macOS, ⌘Q).
- Rouvrir.
- Vérification: taper `/hacienda` dans la zone de saisie doit faire apparaître la liste des commandes (`/hacienda:setup`, `/hacienda:rgpd:registre`, etc.).

If `/hacienda:*` doesn't appear in the slash menu after restart, the troubleshooting section §8 covers the four most likely causes: plugin not enabled, plugin manifest version mismatch, Cowork cache stale, MCP server not registered (re-run Step 2).

---

## Tone, language register, jargon policy

### Vouvoiement throughout

Audience = regulated professionals. Vouvoiement is mandatory. Tone is sober, precise, factual — the register expected by an avocat reading a professional software notice. No "salut", no decorative emojis. The 1–2 functional emojis already used by SKILL.md (`✅`, `📋`, `⚠️`) are preserved when they appear inside copy-pasted output samples.

### The jargon-hiding rule

The reader is not a developer. Every technical term is replaced by its functional name. Translation table applied uniformly across the document:

| Internal technical term | README uses |
|---|---|
| MCP server | "le moteur Hacienda Ghost" |
| serveur, daemon | "le service local" |
| vault | "le coffre-fort local" |
| embedder, embeddings | "moteur de recherche sémantique" |
| GLiNER2, NER, LoRA adapter | "détecteur de PII français" (model name not exposed) |
| RAG, retrieval | "recherche dans vos documents" |
| chunk, chunking | "extrait du document" |
| anonymize, placeholder, token | "remplacement par étiquette" / "étiquette opaque" |
| BM25, vector search | (not mentioned at all) |
| API PISTE | "votre clé Legifrance" |
| schema, Pydantic, JSON | (not mentioned) |
| audit log JSONL | "journal d'audit" |

### Terms preserved as-is

These are part of the avocat's daily vocabulary and removing them would be patronising:

- RGPD, Art. 30, Art. 15, Art. 17, Art. 35
- DPIA, CNIL, JORF, jurisprudence
- secret professionnel, dossier, cabinet
- Legifrance, OpenLégi (named products)
- Claude Desktop, Cowork (named products)

### Phrasing conventions

- **No "we / nous" as authors.** Subject is the user or the software. *"Hacienda Ghost indexe vos documents en local."* / *"Vous générez le registre en une commande."*
- **No heavy subjunctives.** Direct present tense.
- **No "il suffit de"** — almost always lazy phrasing that hides complexity. Say what happens.
- **Version numbers, ports, paths** in `inline code`, never bare in prose.
- **Captions** describe what is observed in the screenshot, not what was done to produce it.

---

## File layout & cleanup

### piighost main repo

| Path | Action | Reason |
|---|---|---|
| `README.md` | **Replaced** (full content rewrite in French) | GitHub primary, PyPI links here, single canonical entry point |
| `README.fr.md` | **Deleted** (`git rm`) | Content folded into new `README.md` |

No image directory is created. Text-only is a deliberate v1 choice (see *Non-goals*). If the screenshots story comes back in a future iteration, `docs/images/readme/` is the path to use.

### plugin worktree (`.worktrees/hacienda-plugin`)

| Path | Action | Reason |
|---|---|---|
| `README.md` | **Deleted** (`git rm` in plugin's own `.git`) | The main piighost README is canonical; the plugin doesn't need its own user-facing README. `plugin.json.description` already advertises capabilities to Claude Desktop. |

### Out of scope (does NOT change)

- `pyproject.toml`: `name = "piighost"`, `version = "0.8.0"` stay. No PyPI rename.
- `plugin.json`: `"name": "hacienda"` stays. No plugin rename.
- Internal command names: `piighost install`, `piighost-mcp` stay. No CLI rename.
- Source code (`src/piighost/`): zero changes. This is a documentation-only phase.
- All other docs (`docs/superpowers/specs/`, `docs/superpowers/plans/`, etc.) — untouched.

---

## The two commits

The work splits cleanly into two atomic commits in two different repos:

**1. piighost main repo (`master` branch):**

```
docs: rewrite README for non-technical Hacienda Ghost users

- Replace README.md with French content for regulated professionals
  (avocats, notaires, médecins, experts-comptables, RH).
- Delete README.fr.md (folded into the single canonical README.md).
- Brand bundle naming: "Hacienda Ghost" for user-facing copy;
  internal package names (piighost, hacienda plugin) unchanged.
- Focus on MCP + plugin install path; --mode=full (proxy) deferred.
- Text-only — no screenshots in v1 (compensated by expected-output
  code blocks throughout install + first-use sections).
```

**2. plugin worktree (`main` branch of hacienda repo):**

```
docs: remove plugin-local README; main piighost README is canonical

The Hacienda Ghost README in the piighost repo now covers the plugin
install + first-use walkthrough end to end. Cowork discovers plugins
via plugin.json, not README, so this deletion is purely a cleanup.
```

---

## Risk register

| Risk | Mitigation |
|---|---|
| `uvx --from piighost piighost install` doesn't work on a clean Windows machine without `uv` | The README's Step 1 installs `uv`. Verified that `uv install` script works on Windows PowerShell. Add a "Si la commande n'est pas reconnue, redémarrez le terminal" note. |
| User runs `claude plugins add jamon8888/hacienda` before installing piighost | Plugin's slash commands politely refuse with "le moteur Hacienda Ghost n'est pas installé" (the existing skills already handle missing-MCP gracefully). README §5 is ordered piighost → plugin to avoid this. |
| User skips the `/hacienda:setup` wizard and goes directly to `/hacienda:rgpd:registre` | Wizard's pre-flight check refuses politely with "Configurez d'abord via /hacienda:setup". README mentions this in §6 step A. |
| PyPI auto-translation of French README is poor for non-French dev users | Acceptable. Bundle naming was confirmed as Option 2: PyPI is not the primary user surface. |
| Plugin worktree README deletion breaks something we forgot | Cowork only reads `plugin.json` (verified). Worth one line in the plugin commit message. |
| Without screenshots, install step "I see something different" creates confusion | Each terminal step ships an *expected-output block* showing what to see. Differs from screenshots by being copy-paste-friendly text. Maintenance cost: zero (the prose is the canonical version). |

---

## Success criteria

The README ships when:

1. A French-speaking avocat unfamiliar with Python can install Hacienda Ghost in ≤ 10 minutes following the README literally — verified by one volunteer test.
2. The 12 slash commands in §7 all match what the plugin v0.8.0 actually exposes — verified by `git -C .worktrees/hacienda-plugin ls-files skills/`.
3. Vouvoiement consistency check — zero "tu" in the body (excluding code samples).
4. Jargon-hiding consistency check — zero occurrences of "MCP", "vault", "embedder", "RAG", "GLiNER2", "BM25" in the user-facing prose (the table in §9 may legitimately mention chiffrement; technical terms allowed only inside code blocks).
5. The 4 install steps in §5 + 3 first-use steps in §6 are reproducible verbatim — every command, env var, and expected-output block is real (verified by re-running the smoke against the multi-format corpus).
6. Plugin install command (`claude plugins add jamon8888/hacienda`) verified against both Cowork-in-Claude-Desktop and Cowork-in-Claude-Code targets.

---

## Estimated effort

| Step | Effort |
|---|---|
| Draft full README in French (~5 screens) | 2 h |
| Capture expected-output samples by re-running the smoke + interactive installer (--dry-run mode for the install assistant, real outputs for first-use steps) | 30 min |
| Self-review pass (vouvoiement, jargon-hiding, code-block sanity, command name accuracy, install step ordering, plugin-install verified on Desktop + Code targets) | 30 min |
| Volunteer test on a clean machine (optional but recommended) | 30 min |
| Cleanup commits in both repos + push | 15 min |
| **Total** | **~3.5 h (half a working day)** |
