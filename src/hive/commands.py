"""Command registry, AI tool schemas, and tool executor."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CommandDoc:
    name: str  # e.g. "/exit"
    usage: str  # e.g. "/model [<name>]"
    description: str
    notes: str | None = None


COMMAND_REGISTRY: list[CommandDoc] = [
    CommandDoc(
        name="/exit",
        usage="/exit",
        description="Exit the application.",
    ),
    CommandDoc(
        name="/language",
        usage="/language",
        description="Open a picker to change the interface language.",
    ),
    CommandDoc(
        name="/model",
        usage="/model [<name>]",
        description=(
            "Show the current AI model. "
            "Optionally switch to a different model by providing a name."
        ),
        notes="The model name must match one available in your Ollama installation.",
    ),
    CommandDoc(
        name="/name",
        usage="/name",
        description="Set or change your display name.",
    ),
    CommandDoc(
        name="/resume",
        usage="/resume",
        description=(
            "Open a picker to resume a previous session. "
            "Restores the session's output and command history."
        ),
    ),
    CommandDoc(
        name="/sessions",
        usage="/sessions",
        description=(
            "List all sessions for this workspace "
            "with their start times and command counts."
        ),
    ),
]

# Bare command names — used for autocomplete and coloring in the TUI.
COMMAND_NAMES: list[str] = [cmd.name for cmd in COMMAND_REGISTRY]

# System prompt: includes the full command list so any model can answer questions about them.
SYSTEM_PROMPT = (
    "You are Hive, an AI assistant running in a terminal application.\n"
    "Users can interact via natural language or use built-in slash commands "
    "(handled by the application, not by you):\n"
    + "\n".join(f"  {cmd.usage}  —  {cmd.description}" for cmd in COMMAND_REGISTRY)
    + "\n\nWhen the user asks about a command, explain what it does. "
    "Never try to execute commands yourself."
)

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _list_commands() -> str:
    lines = [f"  {cmd.usage}  —  {cmd.description}" for cmd in COMMAND_REGISTRY]
    return "\n".join(lines)


def _get_command_info(name: str) -> str:
    if not name.startswith("/"):
        name = "/" + name
    for cmd in COMMAND_REGISTRY:
        if cmd.name == name or cmd.usage.split()[0] == name:
            parts = [f"Usage: {cmd.usage}", f"Description: {cmd.description}"]
            if cmd.notes:
                parts.append(f"Notes: {cmd.notes}")
            return "\n".join(parts)
    return f"Unknown command: '{name}'. Use list_commands to see all available commands."


def run_tool(name: str, args: dict) -> str:
    """Execute an AI tool by name and return the result string."""
    if name == "list_commands":
        return _list_commands()
    if name == "get_command_info":
        return _get_command_info(args.get("name", ""))
    return f"Unknown tool: '{name}'."


# ---------------------------------------------------------------------------
# OpenAI-compatible tool schemas (passed to the AI provider)
# ---------------------------------------------------------------------------

AI_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_commands",
            "description": "List all available slash commands with their usage and brief descriptions.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_command_info",
            "description": "Get detailed information about a specific slash command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The slash command name, e.g. '/model' or '/exit'.",
                    }
                },
                "required": ["name"],
            },
        },
    },
]
