---
name: ask
description: Ask a question about the current Cowork folder. Runs PII-safe hybrid retrieval and returns a cited answer. Equivalent to typing the question in chat, but gives the user an explicit slash-command affordance.
argument-hint: "<question>"
---

# /ask — Question the current folder

```
/ask What are the outstanding deliverables under the 2024 SaaS contract?
```

## Workflow

1. Take `$1` as the user's question. If empty, prompt: *"What would you like to ask about this folder?"*
2. Invoke the `knowledge-base` skill workflow with the question.
3. Return the cited answer.

That's it — this skill exists so the user has a discoverable entry point in the slash-command palette. The real work is in `knowledge-base`.

## Example

```
/ask Who signed the NDA dated 2025-03-12?
```

→ knowledge-base resolves the folder, queries piighost, returns an answer citing `nda-2025-03-12.pdf p.3`.
