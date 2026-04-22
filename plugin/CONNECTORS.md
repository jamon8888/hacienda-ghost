# Connectors

## How tool references work

Hacienda ships with one MCP server: **piighost** (local, stdio-launched, aliased as `hacienda`). It provides retrieval, anonymisation, vault access, and auditing.

Plugin skills also reference generic categories (`~~cloud storage`, `~~email`) when drafting outbound content — these are fulfilled by whatever additional MCP servers the user has configured in Claude Desktop (Box, Egnyte, Gmail, Microsoft 365, etc.). Hacienda is tool-agnostic for outbound: it does not bundle connector MCP servers.

## Connectors for this plugin

| Category | Placeholder | Bundled with hacienda | User-provided options |
|----------|-------------|-----------------------|----------------------|
| Retrieval & PII | `~~retrieval` | **piighost** (required) | — |
| Cloud storage | `~~cloud storage` | — | Box, Egnyte, Dropbox, SharePoint, Google Drive |
| Email | `~~email` | — | Gmail, Microsoft 365 |
| Chat | `~~chat` | — | Slack, Microsoft Teams |
| E-signature | `~~e-signature` | — | DocuSign, Adobe Sign |
| Calendar | `~~calendar` | — | Google Calendar, Microsoft 365 |

The retrieval connector is mandatory. All outbound connectors are optional — hacienda works with zero of them installed (you just won't be able to send redacted drafts directly from chat).

## Installing piighost

`uvx` handles it automatically on first launch — see `.mcp.json`. If `uvx` is not on your PATH, run once:

```bash
pip install piighost
```

Then Cowork's plugin loader will find it via `python -m piighost`.
