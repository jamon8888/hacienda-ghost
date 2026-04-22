# Hacienda — PII-safe RAG for Claude Desktop

> A Cowork plugin that makes Claude Desktop safe to use under professional secrecy.

**Version:** 0.1.0
**License:** MIT (plugin code) — paid support contracts available separately.
**Target users:** avocats, notaires, experts-comptables, médecins, CGP/CIF, conseils en propriété industrielle — any professional bound by *secret professionnel* (Article 226-13 Code pénal) or equivalent confidentiality duty.

## What it does

- Index a client folder (PDF, DOCX, XLSX, emails, notes) locally.
- Answer questions about the folder with cited sources, never sending raw PII to the cloud.
- Redact outbound drafts (emails, Slack, documents) before they leave the device.
- Audit every redaction round-trip per session.

## Why it exists

Raw Claude Desktop ships prompts and files to Anthropic's US-hosted API. For regulated professionals, that breaks secret professionnel. Hacienda wraps the `piighost` MCP server so every prompt that leaves the laptop has been stripped of identifiable data first — and real values come back locally.

The plugin introduces **zero new code** beyond configuration + prose. All logic lives in piighost.

## Installation

### 1. Install from the marketplace

```
claude plugins add anthropics/marketplace/hacienda
```

(Pending official marketplace listing. Meanwhile: `claude plugins add jamon8888/hacienda`.)

### 2. Install piighost (one time)

```bash
# Recommended — with uv (handles extras automatically):
uvx --from piighost piighost --version

# Or via pip:
pip install piighost
```

### 3. Open a client folder in Cowork

Drag a folder onto the Cowork window, or use **File → Open Folder**. Hacienda automatically indexes it and surfaces a status chip.

## Quick start

```
/index              # force-index the current folder
/ask Who signed the NDA dated 2025-03-12?
/status             # index health
/audit              # session redaction report
```

## How it stays safe

1. **Every retrieval result is already redacted.** Piighost's `query` tool replaces PII with placeholders (`«PER_001»`, `«IBAN_003»`) before text reaches the model.
2. **Drafts keep placeholders outbound.** The `redact-outbound` skill tells the model to preserve placeholders in every outbound tool call.
3. **Real values stay local.** Vault is AES-256-GCM on disk; key is in `~/.hacienda/vault.key` or `CLOAKPIPE_VAULT_KEY` env var.
4. **Per-session audit log.** `~/.hacienda/sessions/<session_id>.audit.jsonl` records every round-trip. `/audit` renders it.

## Limitations — honest list

- **No PreToolUse seatbelt.** Cowork plugins don't ship executable hooks (v1). If the user pastes a raw client name into chat, it's up to the skill prose + model discipline to call `anonymize_text` before sending it outbound. We document this explicitly in `skills/redact-outbound/SKILL.md`.
- **One active folder at a time.** Switching folders switches projects — no cross-folder retrieval in v1.
- **Network drives use a 10-minute poll** for change detection. Filesystem watchers are unreliable on SMB/CIFS.
- **Generic skill pack.** Vertical profiles (notaire-specific, médical, etc.) are a paid-support deliverable.

## Paid support

Contact `support@piighost.example` for:
- Onboarding workshops for firms (half-day, remote)
- Vertical profile packs (notaire, avocat, expert-comptable)
- SLA / priority support contracts
- On-premise deployment

---

# Hacienda — RAG confidentiel pour Claude Desktop

> Un plugin Cowork qui rend Claude Desktop compatible avec le secret professionnel.

**Pour qui :** avocats, notaires, experts-comptables, médecins, CGP/CIF, conseils en propriété industrielle — tout professionnel soumis au secret professionnel (article 226-13 du Code pénal) ou à une obligation équivalente.

## Ce que fait Hacienda

- Indexe localement un dossier client (PDF, DOCX, XLSX, emails, notes).
- Répond à vos questions sur le dossier avec citations, sans jamais envoyer de données identifiables dans le cloud.
- Anonymise les brouillons sortants (emails, Slack, documents) avant tout envoi.
- Trace chaque session : quelles données ont été anonymisées, quels tokens sont sortis, lesquels sont revenus.

## Installation

```
claude plugins add anthropics/marketplace/hacienda
pip install piighost
```

Puis ouvrez un dossier client dans Cowork.

## Commandes

```
/index              # forcer l'indexation
/ask Quelles sont les échéances du contrat SaaS 2024 ?
/status             # état de l'index
/audit              # rapport de session
```

## Support payant

Contacts commerciaux : `support@piighost.example` (workshops d'onboarding, profils métiers, SLA, déploiement on-premise).
