---
name: redact-outbound
description: Rules for handling PII placeholders (like «PER_001», «ORG_014», «IBAN_003») when drafting outbound content — emails, Slack messages, document writes, webfetch payloads. Use whenever text derived from the current folder will leave the user's device. Placeholders are INTENTIONAL and must be preserved in outbound payloads; do not rehydrate them.
---

# redact-outbound — Placeholder handling rules

## Why placeholders exist

Piighost replaces PII with opaque tokens before any text reaches the model context. The real values are stored encrypted in a local vault. This means the model's working context is already safe to send to Anthropic's API — but drafts the user writes *back* out (replies, documents, external tool calls) must keep placeholders intact so nothing sensitive leaves the device.

## Placeholder format

```
«<LABEL>_<NNN>»      example: «PER_001», «ORG_014», «IBAN_003», «EMAIL_007»
```

- Always three digits, zero-padded.
- The label vocabulary: `PER`, `ORG`, `LOC`, `EMAIL`, `PHONE`, `IBAN`, `SIREN`, `NIR`, `DATE_DOB`. Other labels may appear — treat any `«LABEL_NNN»` pattern as a placeholder.
- Deterministic per `(project, real_value)`: the same IBAN always becomes the same `«IBAN_NNN»` within one project.

## Rules when drafting outbound content

1. **Keep placeholders verbatim.** Do not remove them. Do not prefix them (*"Mr. «PER_001»"* is wrong — the placeholder already represents the full personal reference).
2. **Do not rehydrate for outbound.** If you need to show the user a real value on their screen (not in an outbound payload), call `mcp__hacienda__rehydrate_text` on the preview string only. The outbound payload keeps the placeholder.
3. **If the user types a real name in chat**, call `mcp__hacienda__anonymize_text` on any text you incorporate into an outbound draft, including the user's words, before sending.
4. **For every outbound tool call**, append a `session_audit_append` event with `session_id=<project>` (the project hash returned by `resolve_project_for_folder` / `bootstrap_client_folder`), `event="outbound"`, `payload={"tool": <name>, "n_placeholders": <count>}`. Never include the raw payload text in the audit.

## Tools that count as "outbound"

Any of:
- `Write`, `Edit`, `MultiEdit` when writing outside the Cowork folder
- `WebFetch`, `WebSearch`
- Any MCP tool whose name contains `slack`, `gmail`, `email`, `mail`, `drive`, `docusign`, `sign`, `webhook`, `post`

When in doubt, treat the tool as outbound.

## Example

User: *"Reply to Jean Martin's email from Monday saying we'll send the contract by Friday."*

Your draft outbound payload:
```
Cher «PER_001»,

Merci pour votre email. Nous vous transmettrons le contrat d'ici vendredi.

Cordialement,
```

The `To:` field uses a placeholder email (`«EMAIL_007»`) pulled from the original email, not a raw address.

When the user reads the draft in Cowork, the plugin may rehydrate `«PER_001»` → `Jean Martin` for display only. The actual outbound tool call carries the placeholder.
