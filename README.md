# Hive

An interactive CLI tool built with `prompt_toolkit` and `rich`.

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
| `--session <id>` | — | Resume a previous session |
| `--list-sessions` | — | Print sessions for the current directory and exit |

**Log levels:** `DEBUG`, `INFO`, `WARNING`, `ERROR`

## Examples

```bash
hive                                      # start or resume workspace in current directory
hive --list-sessions                      # show all sessions for this directory
hive --session a3f9b2                     # resume session a3f9b2
hive --log DEBUG                          # verbose console output
hive --log-path ./logs/hive.log           # custom log file location
```

## Workspace

On first run in a directory, hive asks whether to create a local `.hive/` workspace. Press **Y** to confirm or **N** to exit. Once trusted, every subsequent `hive` invocation in that directory starts a new session automatically.

Each session stores its history, full output, and log in `.hive/<session-id>/`. Run `/sessions` inside the TUI or `hive --list-sessions` to see all sessions.

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
