# Hive Backlog

## Immediate
- [x] Update README — document all current features, commands, install options
- [x] Manual testing — run through the full app flow before implementing new features

## Planned Features
- [x] Command highlighting — slash commands in the input field (e.g. `/resume`, `/language`) rendered with syntax highlighting
- [x] Auto-suggestions — show available slash commands as the user types, selectable with Tab or arrow keys
- [x] MCP server interface — define an interface that MCP servers can implement to register custom GUI elements or trigger actions within Hive (e.g. custom panels, status indicators, input handlers)
- [x] Interchangeable AI backend — a provider interface that routes user input to an AI (default: Ollama) and displays the response; model and provider configurable per-project; designed so alternative backends (e.g. OpenAI-compatible) can be swapped in
- [x] Lightweight agents — goal-oriented agentic loops (plan → tool call → observe → repeat) with /agent list/add/delete/edit commands, built-in shell-task agent, Ctrl+C abort
- [x] Shell tool — AI can run shell commands in the workspace CWD
- [x] MCP status in welcome panel — connected server names shown live

## External MCPs to integrate
- [ ] GitHub MCP (official, `npx @github/github-mcp-server`) — PR reviews, issue management, commenting without leaving terminal
- [ ] Fetch/Web MCP (official Anthropic) — let AI look up docs, Stack Overflow, changelogs mid-conversation

## New MCPs to build
- [ ] **project-context** — per-project scratchpad: current goal, open questions, notes, links; survives across Hive sessions; makes agents aware of developer intent
- [ ] **dev-log** — append-only daily developer journal: decisions made, blockers hit, follow-ups; searchable; pairs with engra for semantic search over history
- [ ] **code-search** — ripgrep-based structured code search returning `{file, line, match}` JSON; better token efficiency than raw shell output; supports multi-project search

## Hive Core Improvements
- [ ] AnthropicProvider — alternative AI backend using Claude API; enables Claude-quality agents while keeping Ollama for regular chat
- [ ] Auto-create `.gitignore` on workspace trust — when `.hive/` is created in a git repo, automatically ignore session directories
- [ ] Gitscribe fallback warning — one-time warning on startup if `ANTHROPIC_API_KEY` is not set and gitscribe is connected
