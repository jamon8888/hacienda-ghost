---
name: status
description: Show the index state of the folder currently open in Cowork — how many files are indexed, when the last update happened, any errors encountered. Use when the user wants a health check before asking questions, or when troubleshooting unexpected retrieval results.
---

# /status — Folder health

```
/status
```

## Workflow

1. Call `mcp__hacienda__resolve_project_for_folder(folder=<active>)` → `folder, project`.
2. Read `piighost://folders/{b64_path}/status` (resource URIs keep the server-declared `piighost://` scheme; the Cowork alias only rewrites tool-name prefixes).
3. Render:

```
Folder:       <absolute path>
Project:      <project hash>
State:        <ready|empty>
Indexed docs: <total_docs>
Chunks:       <total_chunks>
Last update:  <last_update ISO 8601> (or "never" when null)
Errors:       <n> (list up to 5, then "...and <n-5> more")
```

4. If `state == "empty"`, suggest `/index` to the user.
5. If `last_update` is older than 10 minutes on a network drive, suggest `/index incremental`.
