# Hive Backlog

## Immediate
- [x] Update README — document all current features, commands, install options
- [x] Manual testing — run through the full app flow before implementing new features

## Planned Features
- [x] Command highlighting — slash commands in the input field (e.g. `/resume`, `/language`) rendered with syntax highlighting
- [x] Auto-suggestions — show available slash commands as the user types, selectable with Tab or arrow keys
- [ ] MCP server interface — define an interface that MCP servers can implement to register custom GUI elements or trigger actions within Hive (e.g. custom panels, status indicators, input handlers)
- [x] Interchangeable AI backend — a provider interface that routes user input to an AI (default: Ollama) and displays the response; model and provider configurable per-project; designed so alternative backends (e.g. OpenAI-compatible) can be swapped in
