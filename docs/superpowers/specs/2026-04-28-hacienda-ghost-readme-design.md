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
- GIFs or animated content. v1 is text + 4 PNG screenshots only.

---

## Audience

**Primary:** French regulated professional, comfortable with email and Word, has installed Claude Desktop, has never run a Python tool. Will paste two commands the README provides verbatim. Will not edit JSON config files. Will not read past the install section if the install fails.

**Reading device:** desktop browser on github.com or a hosted page. Not phone, not e-reader.

**Reading mode:** "scan first, read what matters, paste commands". The README must look skimmable — short paragraphs, bullets, code blocks set off clearly.

---

## Document structure (locked)

11 sections, ~6 screens of vertical scroll, 4 PNG screenshots:

| § | Title | Length | Includes |
|---|---|---|---|
| 1 | Hacienda Ghost en bref | ~3 lines | One-sentence hook + 1-line context |
| 2 | Ce que ça fait pour vous | ~10 lines | 4 capability bullets |
| 3 | Garantie de confidentialité | ~5 lines | What stays local / what goes outbound / what never leaves |
| 4 | Prérequis | 3 bullets | OS, Claude Desktop, terminal access |
| 5 | Installation en 4 étapes | ~30 lines + 1 screenshot | Numbered steps, paste-and-go |
| 6 | Premier usage en 3 étapes | ~30 lines + 3 screenshots | Wizard → indexing → registre PDF |
| 7 | Toutes les commandes | 1 table (~12 rows) | Slash commands quick reference |
| 8 | Que faire si… | ~20 lines | 4 troubleshooting Q&As |
| 9 | Sécurité et confidentialité | ~10 lines | File locations, encryption, audit log |
| 10 | Support | ~5 lines | GitHub issues, paid contracts |
| 11 | Licence | 1 line | MIT |

The full outline detail (with sample prose for §2 and §5.2) is in Brainstorming Section 1.

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
| `docs/images/readme/install-wizard.png` | **Created** | Screenshot 1 — install assistant at review screen |
| `docs/images/readme/setup-wizard.png` | **Created** | Screenshot 2 — `/hacienda:setup` mid-conversation in Claude Desktop |
| `docs/images/readme/cowork-status-chip.png` | **Created** | Screenshot 3 — Cowork status chip "14 docs indexés" |
| `docs/images/readme/registre-art30.png` | **Created** | Screenshot 4 — rendered Art. 30 PDF first page (avocat-flavored header visible) |

The 4 screenshots are capturable from existing infrastructure:
- Install assistant: `uvx --from piighost piighost install --mode=mcp-only --dry-run` in a Windows Terminal
- Setup wizard: walk through Step 1–6 in Claude Desktop with the daemon running
- Cowork status chip: any indexed folder produces it; the multi-format corpus from earlier smoke tests works
- Art. 30 PDF: render an existing `processing_register` output via `render_compliance_doc(profile="avocat", format="pdf")`

All four are 30 minutes total to capture once the daemon is running.

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
- Add 4 PNG screenshots under docs/images/readme/.
- Brand bundle naming: "Hacienda Ghost" for user-facing copy;
  internal package names (piighost, hacienda plugin) unchanged.
- Focus on MCP + plugin install path; --mode=full (proxy) deferred.
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
| Screenshots drift from reality on each release | Capture them last, after a `git tag v0.8.0`. Re-capture on each minor bump. Worth ~30 min/release. |
| `uvx --from piighost piighost install` doesn't work on a clean Windows machine without `uv` | The README's Step 1 installs `uv`. Verified that `uv install` script works on Windows PowerShell. Add a "Si la commande n'est pas reconnue, redémarrez le terminal" note. |
| User skips the `/hacienda:setup` wizard and goes directly to `/hacienda:rgpd:registre` | Wizard's pre-flight check refuses politely with "Configurez d'abord via /hacienda:setup". README mentions this in §6 step A. |
| PyPI auto-translation of French README is poor for non-French dev users | Acceptable. Bundle naming was confirmed as Option 2: PyPI is not the primary user surface. |
| Plugin worktree README deletion breaks something we forgot | Cowork only reads `plugin.json` (verified). Worth one line in the plugin commit message. |

---

## Success criteria

The README ships when:

1. A French-speaking avocat unfamiliar with Python can install Hacienda Ghost in ≤ 10 minutes following the README literally — verified by one volunteer test.
2. The 4 screenshots match the actual UX on a clean machine — verified by re-capturing them at release.
3. The 12 slash commands in §7 all match what the plugin v0.8.0 actually exposes — verified by `git -C .worktrees/hacienda-plugin ls-files skills/`.
4. Vouvoiement consistency check — zero "tu" in the body (excluding code samples).
5. Jargon-hiding consistency check — zero occurrences of "MCP", "vault", "embedder", "RAG", "GLiNER2", "BM25" in the user-facing prose (the table in §9 may legitimately mention chiffrement; technical terms allowed only inside code blocks).

---

## Estimated effort

| Step | Effort |
|---|---|
| Capture 4 screenshots | 30 min |
| Draft full README in French (~6 screens) | 2 h |
| Self-review pass (vouvoiement, jargon-hiding, code-block sanity, command name accuracy) | 30 min |
| Volunteer test on a clean machine (optional but recommended) | 30 min |
| Cleanup commits in both repos + push | 15 min |
| **Total** | **~3.5 h (half a working day)** |
