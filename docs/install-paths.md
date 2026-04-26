# Install paths: install script vs MCPB bundle

piighost ships two parallel installation channels. They produce
overlapping but not identical end states.

## Quick comparison

|                          | Install script (`curl \| bash`) | MCPB bundle (drag-drop) |
|--------------------------|---------------------------------|-------------------------|
| Audience                 | terminal users                  | GUI-only users          |
| Bootstrap                | `curl ... \| bash`              | drag `.mcpb` onto Claude Desktop |
| Anonymizing proxy        | included in `--mode=full`       | not available           |
| Auto-restart on login    | yes (LaunchAgent / systemd `--user` / schtasks `/onlogon`) | N/A — Claude Desktop manages the extension |
| Vault dir                | user-chosen (default `~/.piighost/vault`) | configured at first install (`${user_config.vault_dir}`) |
| MCP server               | registered in your chosen client(s) | isolated to Desktop's extension sandbox |
| Removal                  | `piighost uninstall`            | Claude Desktop → Settings → Extensions → Remove |

## When to pick which

- **You use Claude Code (terminal CLI agent)** → install script. Only path that registers piighost in `~/.claude/settings.json`.
- **You only use Claude Desktop and don't want a terminal** → MCPB bundle (`piighost-full.mcpb` for RAG, `piighost-core.mcpb` for anonymize-only).
- **You want anonymizing proxy interception of `api.anthropic.com`** → install script with `--mode=full`. Not available via MCPB.
- **You use both Claude Code and Claude Desktop** → install script registers MCP in both.

## Recovery

The install script's `--mode=full` sets `ANTHROPIC_BASE_URL=https://localhost:8443` in Claude Code's settings. If the local proxy stops:

- `piighost connect` / `piighost disconnect` toggle the env var without editing JSON.
- `piighost doctor` detects the case and prints fix options.
- Last-resort: edit `~/.claude/settings.json` and remove `env.ANTHROPIC_BASE_URL`.

The MCPB path doesn't set `ANTHROPIC_BASE_URL` — it can't, because Claude Desktop ignores env vars in extension config. Removing the bundle is the only "off switch" for the MCPB path.

## Coexistence

Both channels can be installed at the same time. They produce two independent MCP server registrations (script-installed appears as `piighost`, MCPB appears as `piighost-full` or `piighost-core` depending on which bundle). Claude Desktop will run whichever is enabled in the Extensions panel.

## Windows notes

The `--mode=full` user-level auto-restart on Windows uses Scheduled Task with `/onlogon` trigger. Windows lacks a native unprivileged equivalent of macOS LaunchAgent's `KeepAlive`, so the task only fires at logon. If the daemon crashes mid-session it will not restart until the next logon. Workarounds:

- Run `piighost serve` from a terminal in long-lived dev sessions.
- Use `--mode=strict` (with admin) when uptime matters — strict registers a system service that survives crashes.

The kreuzberg dependency (used for binary document extraction) has no Windows wheels and is platform-gated out of the `[index]` extra. Plain text formats (`.txt`, `.md`, `.rst`, `.html`, `.htm`, `.eml`) still index correctly via the stdlib fallback. PDFs / Office documents will fail extraction on Windows until kreuzberg ships Windows support.
