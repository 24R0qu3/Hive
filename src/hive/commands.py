"""Command registry, AI tool schemas, and tool executor."""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path


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
    CommandDoc(
        name="/mcp",
        usage="/mcp [manage]",
        description=(
            "List connected MCP servers and their tools. "
            "Use '/mcp manage' to open the interactive server manager."
        ),
    ),
    CommandDoc(
        name="/use",
        usage="/use [<server> | all | none]",
        description=(
            "Activate full MCP tool schemas for the AI. "
            "Without an argument, shows currently active servers. "
            "Use '/use <name>' to toggle a server on or off, "
            "'/use all' to activate all connected servers, "
            "'/use none' to deactivate all."
        ),
        notes=(
            "Active servers' full tool schemas are included in every AI request. "
            "A compact tool listing is always visible to the model regardless of activation."
        ),
    ),
    CommandDoc(
        name="/agent",
        usage="/agent <name> <goal>  |  /agent list  |  /agent add  |  /agent delete <name>  |  /agent edit <name>  |  /agent copy <name> local|global",
        description=(
            "Run a named agent on a goal. "
            "Use '/agent list' to see available agents, "
            "'/agent add' to define a new one, "
            "'/agent delete' to remove one, "
            "'/agent edit' to open its Markdown file in your editor, "
            "'/agent copy' to copy an agent between local and global scope."
        ),
        notes=(
            "Agents run autonomously using tools until the goal is complete "
            "or the step limit is reached. Press Ctrl+C to abort a running agent."
        ),
    ),
]

# Bare command names — used for autocomplete and coloring in the TUI.
COMMAND_NAMES: list[str] = [cmd.name for cmd in COMMAND_REGISTRY]

# Sub-commands for commands that accept a second token.
SUB_COMMANDS: dict[str, list[str]] = {
    "/agent": ["add", "list", "delete", "edit", "copy"],
    "/mcp": ["manage"],
    "/use": ["all", "none"],
}

# System prompt: includes the full command list so any model can answer questions about them.
SYSTEM_PROMPT = (
    "You are Hive, an AI assistant running in a terminal application.\n"
    "Users can interact via natural language or use built-in slash commands "
    "(handled by the application, not by you).\n\n"
    "This is the COMPLETE and EXHAUSTIVE list of slash commands — no others exist:\n"
    + "\n".join(f"  {cmd.usage}  —  {cmd.description}" for cmd in COMMAND_REGISTRY)
    + "\n\nRules:\n"
    "- Never mention, suggest, or describe a command that is not in the list above.\n"
    "- If a user asks about a command that is not in the list, tell them it does not exist.\n"
    "- Shell commands: when the user asks you to run anything in the terminal, inspect files, "
    "or check system state — call the 'shell' tool immediately. Do NOT describe what command "
    "to run. Do NOT show a code block. Call the tool and show the real output.\n"
    "  Example: user says 'get repo status' → call shell(command='git status'), show output.\n"
    "- Slash commands (like /agent) are typed by the USER in the input field. You cannot "
    "invoke slash commands yourself. If the user asks you to run a named agent (e.g. "
    "'run agent git-helper', 'use agent X', 'execute agent Y'), respond ONLY with: "
    "'Type this in the input field: /agent <name> <goal>' — do not attempt to use tools yourself.\n"
    "- When asked what commands are available, list only the commands above.\n"
    "- MCP servers are listed in the context when connected. Their full tool schemas are only "
    "included when the user activates them with /use <name>. If a user asks to do something "
    "that requires an MCP tool and no schemas are active, tell them to run /use <server-name> first.\n"
    "- MCP tools are NEVER CLI commands. They are callable only via the tool-call mechanism "
    "(names follow the pattern servername__toolname, e.g. gitmcp__stage_all). "
    "Never suggest running an MCP tool name as a bash or shell command."
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
    return (
        f"Unknown command: '{name}'. Use list_commands to see all available commands."
    )


def _run_shell(command: str, cwd: Path | None) -> str:
    try:
        if platform.system() == "Windows":
            # Use PowerShell 7 (pwsh) for rich command support (ls, pwd, cat, etc.).
            # Fall back to cmd.exe if pwsh is not installed.
            try:
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    timeout=30,
                )
            except FileNotFoundError:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    timeout=30,
                    shell=True,
                )
        else:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=30,
                shell=True,
            )
        output = result.stdout
        if result.stderr:
            output += result.stderr
        return output if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as exc:
        return f"Error: {exc}"


def run_tool(name: str, args: dict, cwd: Path | None = None) -> str:
    """Execute an AI tool by name and return the result string."""
    if name == "list_commands":
        return _list_commands()
    if name == "get_command_info":
        return _get_command_info(args.get("name", ""))
    if name == "shell":
        return _run_shell(args.get("command", ""), cwd)
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
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": (
                "Run a shell command in the current working directory and return its output. "
                "Use this for ANY request that requires real data: git status, file contents, "
                "directory listings, environment variables, running scripts, etc. "
                "Always call this tool instead of describing or suggesting a command."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run, e.g. 'ls', 'pwd', 'cat README.md'.",
                    }
                },
                "required": ["command"],
            },
        },
    },
]
