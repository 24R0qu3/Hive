# Hive

An interactive full-screen CLI tool built with `prompt_toolkit` and `rich`.

## Installation

### Option 1 — pipx (recommended)

[pipx](https://pipx.pypa.io) installs the tool in an isolated environment and puts `hive` on your PATH automatically.

```bash
pipx install git+https://github.com/24R0qu3/Hive.git
```

### Option 2 — one-liner install script

Downloads the latest prebuilt binary from GitHub Releases and places it on your PATH.

**macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/24R0qu3/Hive/main/install.sh | sh
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/24R0qu3/Hive/main/install.ps1 | iex
```

The scripts install to `~/.local/bin` (macOS/Linux) or `%USERPROFILE%\bin` (Windows) and add that directory to your user PATH if it isn't there already.

## Usage

```bash
hive [OPTIONS]
```

## Options

| Flag | Default | Description |
|---|---|---|
| `--log` | `WARNING` | Console log level |
| `--log-file` | `DEBUG` | File log level |
| `--log-path` | platform default | Path to log file |
| `--resume <id>` | — | Resume a previous session by ID |
| `--list-sessions` | — | Print all sessions for the current directory and exit |

**Log levels:** `DEBUG`, `INFO`, `WARNING`, `ERROR`

## Examples

```bash
hive                          # start a new session (or resume if already trusted)
hive --list-sessions          # show all sessions for this directory
hive --resume a3f9b2          # resume session a3f9b2
hive --log DEBUG              # verbose console output
hive --log-path ./logs/hive.log  # custom log file location
```

## First-run flow

When you run `hive` for the first time ever, it will:

1. **Ask for your name** — stored globally so it only happens once across all projects. Your name appears as a greeting in the welcome panel.
2. **Ask to trust the directory** — use `←` / `→` to choose **Yes** or **No**, then press `Enter`. Choosing Yes creates a `.hive/` workspace in the current directory.
3. **Ask for a language** — choose between English and Deutsch with `↑` / `↓`, then press `Enter`. The choice is stored per project in `.hive/config.json`.

On every subsequent run in a trusted directory all three steps are skipped and a new session starts immediately.

## Commands

Type a command in the input field and press `Enter`:

| Command | Description |
|---|---|
| `/sessions` | Show a table of all sessions for the current directory |
| `/resume` | Open an inline session picker to switch to a previous session |
| `/language` | Re-open the language picker to change the project language |
| `/name` | Change your display name |
| `/model <name>` | Set the AI model for this session (e.g. `/model mistral`) |
| `/mcp` | List connected MCP servers and their tools |
| `/mcp manage` | Open the interactive MCP server manager |
| `/agent list` | List all available agents |
| `/agent <name> <goal>` | Run a named agent on a goal |
| `/agent add` | Define a new custom agent via a step-by-step wizard |
| `/agent delete <name>` | Delete a user-defined agent |
| `/agent edit <name>` | Open a user-defined agent's Markdown file in your editor |
| `/exit` | Exit Hive |

As you type, a suggestion bar appears below the input showing matching commands. Use `Tab` or `↑`/`↓` to select, `Enter` to accept. Sub-commands are suggested automatically once you complete a command — e.g. typing `/agent ` shows `add`, `list`, `delete`, `edit`. Both the command and its sub-command are highlighted in the input field.

**Keyboard shortcuts in the input field:**

| Key | Action |
|---|---|
| `↑` / `↓` | Navigate command history (or move cursor in multi-line input) |
| `Ctrl+J` | Insert a newline (multi-line input) |
| `PageUp` / `PageDown` | Scroll through output |
| `Ctrl+C` | Abort a running agent (first press), or exit (press twice) |
| `Ctrl+D` | Exit |

## Workspace

On first run in a directory, Hive asks whether to create a local `.hive/` workspace. Once trusted, every subsequent `hive` invocation in that directory starts a new session automatically.

Each session gets its own subdirectory under `.hive/<session-id>/` containing:

| File | Contents |
|---|---|
| `meta.json` | Session ID, start timestamp, working directory |
| `history` | Command history (JSON-lines) |
| `output` | Full output of the session (JSON-lines) |
| `hive.log` | Per-session log file |

When you exit, Hive prints the session ID so you can resume it later:

```
Resume with: hive --resume a3f9b2
```

## AI backend

Hive routes every non-command message to a local [Ollama](https://ollama.com) instance for a multi-turn conversation.

On startup, Hive checks that Ollama is reachable and that required API keys are set. If Ollama is not running, a yellow warning appears in the output area instead of crashing. If a `gitscribe` MCP server is configured but `ANTHROPIC_API_KEY` is missing, a one-time warning is shown.

**Requirements:** Ollama must be running locally (`ollama serve`) and a model must be pulled:

```bash
ollama pull llama3.2
```

The default model is `llama3.2` and can be overridden per project with `/model <name>`. The choice is saved in `.hive/config.json` and restored on resume.

While the model is thinking, Hive shows an animated status line with the elapsed time. The full conversation history is preserved in-session for multi-turn context, and the AI response is displayed directly in the output area.

### Swapping backends

The AI layer is defined by a `typing.Protocol`:

```python
class AIProvider(Protocol):
    def chat(self, messages: list[dict], model: str) -> str: ...
```

Pass any object satisfying this protocol as `provider` when constructing `HiveApp` to use an alternative backend (OpenAI-compatible APIs, mock providers for testing, etc.).

## Agents

Agents are goal-oriented AI loops that autonomously plan, call tools, observe results, and repeat until the goal is complete or a step limit is reached.

### Built-in agents

| Agent | Description | Tools |
|---|---|---|
| `shell-task` | Execute multi-step shell operations to accomplish a stated goal | `shell` |

### Running an agent

```
/agent shell-task create a new branch called feature/auth and scaffold a basic FastAPI app
```

The agent shows each step with a `[N/max]` counter in the output area as it works. Each tool call shows the tool name, arguments preview, and result. Press `Ctrl+C` to abort a running agent.

The agent also receives context automatically: current OS, working directory, and current git branch (if in a git repo).

### Managing agents

| Command | Description |
|---|---|
| `/agent list` | Show all available agents (built-in + custom) |
| `/agent add` | Start a step-by-step wizard to create a new agent |
| `/agent delete <name>` | Remove a user-defined agent |
| `/agent edit <name>` | Open the agent's Markdown file in your system editor (`$EDITOR`) |

### Adding a custom agent

Run `/agent add` to start an interactive wizard. You will be prompted for:

1. **Name** — identifier used in `/agent <name> <goal>`
2. **Description** — shown in `/agent list`
3. **System prompt** — instructions for the agent (use `Ctrl+J` for newlines)
4. **Tools** — comma-separated tool names to restrict the agent to (empty = all tools)
5. **Max steps** — hard cap on autonomous iterations (default: 10)

Custom agents are saved to `.hive/agents/<name>.md` and can be version-controlled alongside your project.

You can also create agent files manually:

```markdown
---
name: my-agent
description: Does something useful
tools:
  - shell
max_steps: 10
stop_phrase: TASK_COMPLETE
---

You are an agent that...
When done, say TASK_COMPLETE.
```

Place the file in `.hive/agents/my-agent.md` and it will appear in `/agent list` immediately. Existing `.json` agent files are migrated to `.md` automatically on first load.

### MCP tools in agents

Agents have access to all connected MCP servers. To restrict an agent to specific MCP tools, list the prefixed names (e.g. `gitmcp__commit`, `gitscribe__generate_commit_message`) in the `tools` field.

## MCP servers

Hive connects to external [MCP](https://modelcontextprotocol.io) servers and exposes their tools to the AI and to agents.

### Connecting a server

Run `/mcp manage` and press `A` to add a new server. You will be prompted for the executable path, arguments, and optional environment variables. Servers are stored in `.hive/mcp.json`.

Connected servers are shown in the welcome panel (`⬡ gitmcp, gitscribe`) and update live as servers connect. Use `/mcp` to see a tool count per server.

### Tool naming

Tools from MCP servers are prefixed with the server name: `gitmcp__commit`, `gitscribe__generate_commit_message`, etc. This prevents collisions and lets you restrict agents to specific servers via the `tools` field.

## Log file location

By default logs are written to the platform-appropriate user directory:

- **Windows:** `%LOCALAPPDATA%\hive\Logs\hive.log`
- **macOS:** `~/Library/Logs/hive/hive.log`
- **Linux:** `~/.cache/hive/log/hive.log`

## Development

```bash
pip install -e ".[test]"   # install with test dependencies
pip install -e ".[dev]"    # install with dev dependencies (bump-my-version, ruff)
pytest                     # run tests
ruff check .               # lint
ruff format .              # format code
```

## Releasing

```bash
bump-my-version bump patch   # 0.0.0 → 0.0.1
bump-my-version bump minor   # 0.0.1 → 0.1.0
bump-my-version bump major   # 0.1.0 → 1.0.0
git push --follow-tags       # triggers release workflow
```

## CI / CD

- **test.yaml** — runs ruff and pytest on every push/PR to `main`
- **release.yaml** — builds executables for Windows, Linux, macOS on version tag push
- **Dependabot** — opens weekly PRs to update pip and GitHub Actions dependencies
