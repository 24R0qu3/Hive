---
name: Hive project architecture
description: Key architecture decisions and gotchas in the Hive TUI codebase
type: project
---

Hive is a terminal AI chat app built with prompt_toolkit + rich + Ollama.

**Layout** (HSplit): output window → Frame(input field) → hints window

**Key files:**
- `src/hive/ui/app.py` — main TUI, `HiveApp` class
- `src/hive/commands.py` — single source of truth for slash commands, AI tool schemas
- `src/hive/i18n.py` — EN/DE translation strings
- `src/hive/ai.py` — `OllamaProvider` with tool-call loop

**Output height calculation (`_output_height`):**
Must subtract: input_h + 2 (frame borders) + hints_h (≥1 reserved row for transient hint + n command completions).
Forgetting hints_h causes output to render behind the input/hints area.

**hints_window** is always visible (not a ConditionalContainer) — permanently reserves 1 row for transient hints so layout never shifts.

**Welcome screen scrolling:**
`welcome_padded = welcome_lines + [""] * max(0, available - len(welcome_lines))`
Then `all_lines = welcome_padded + output_lines`, always show last `available` lines.
This keeps welcome top-anchored with no output, and lets output push it upward without a jump.

**Mouse scroll:** Uses `_ScrollableWindow` subclass (overrides `_mouse_handler`) for the output window. Input field window is patched via instance attribute (no public API).

**Shift+Enter was removed** — newline is Ctrl+J only. ANSI_SEQUENCES mapping was removed.

**Double Ctrl+C to exit** — 1 second window. First press shows transient hint "Press Ctrl+C again to exit" which clears via `threading.Timer(1.0, ...)`.

**prompt_toolkit internals used:**
- `Window._mouse_handler` (instance patch on input_field.window)
- These are fragile; see comments in app.py.
