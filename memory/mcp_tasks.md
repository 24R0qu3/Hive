---
name: MCP feature tasks
description: Planned tasks for full MCP client support in Hive (Task 1 done)
type: project
---

Task 1 is complete. Remaining tasks below.

**Why:** Hive acts as an MCP client — it speaks the MCP protocol to servers, translates their tools into Ollama-compatible schemas, and feeds them into the existing tool-call loop. Goal: every MCP server should work.

---

## Task 2 — Config management commands

Add subcommands to `/mcp` for managing servers without editing `mcp.json` by hand.

- `/mcp list` — table of all configured servers (connected / disabled / error) with tool count
- `/mcp add <name> <command> [args…]` — add a stdio server, persist to `.hive/mcp.json`, connect immediately
- `/mcp remove <name>` — disconnect and remove from config
- `/mcp enable <name>` / `/mcp disable <name>` — toggle without removing; persist change
- Update `commands.py` registry entry for `/mcp` with subcommand usage docs
- Update i18n strings for all new output messages

**How to apply:** `/mcp` with no args currently prints a table of connected servers. Extend `handle_input` to parse subcommands from the text after `/mcp `.

---

## Task 3 — Interactive picker UI

Replace the plain `/mcp` table with an interactive panel (same pattern as model/resume pickers).

- `build_mcp_panel()` in `panels.py` — lists servers with status indicator and tool count; selected row highlighted
- `/mcp` with no args opens the picker
- Up/Down to navigate, Enter to toggle enable/disable, `d` to delete, Esc/Ctrl+C to close
- Add `_picking_mcp`, `_mcp_list`, `_mcp_idx`, `_mcp_panel_key` state to `HiveApp`
- Add key bindings under `_mcp_active` condition
- Add `_get_fragments` branch for the panel
- Update `_not_modal` / `_not_picker` to include `_picking_mcp`

---

## Task 4 — HTTP + SSE transport

Extend `MCPManager` to support remote MCP servers over HTTP+SSE in addition to stdio.

- Add `transport: str` field to `MCPServerConfig` (`"stdio"` | `"sse"`)
- Add `url: str | None` field for SSE servers
- `_connect_async` branches on transport: uses `mcp.client.sse.sse_client` for SSE
- `/mcp add --url <url> <name>` path in Task 2 commands
- i18n strings for SSE-specific errors

---

## Task 5 — Resources

Expose MCP resources as context injected into the conversation.

- `MCPManager.list_resources()` — returns all resources from connected servers
- `MCPManager.read_resource(uri)` — fetches resource content
- Inject relevant resource contents as a system message before the user turn
- Decide strategy: inject all resources (small ones) or let the AI request them via a tool

---

## Task 6 — Prompts

Expose MCP prompts so users can invoke them.

MCP servers can expose prompts via the `prompts/get` endpoint. When invoked, the server runs a function (e.g. fetching live config, querying a service) and returns a formatted string back to the client. Example: Murmur's `murmur_settings` prompt connects to its daemon socket, reads the live config, and returns markdown.

- `MCPManager.list_prompts()` — calls `prompts/list` on each connected server, returns `{server: [prompt_name, …]}`
- `MCPManager.get_prompt(server, name, args)` — calls `prompts/get`, returns the rendered string
- Surface available prompts via `/mcp prompts` subcommand (Task 2 extension) — lists all prompts across servers
- Invoke a prompt: `/mcp prompt <server> <name> [args]` — fetches and prints the result to output
- Or register prompts dynamically as slash commands in `_COMMANDS` so they appear in autocomplete

---

## Design decisions already made

- Tool names prefixed: `servername__toolname` to avoid collisions
- Connection errors print as warnings to output area (not silent, not fatal)
- All enabled servers connect at startup in background threads
- Future: per-server startup vs lazy connect toggle (not in scope yet)
- Official `mcp` Python SDK used for all protocol handling
