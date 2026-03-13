# Python CLI Project Setup Prompt

You are helping set up a modern Python CLI project from scratch. Follow these phases in order.

---

## Phase 1 — Research

Before doing anything, search for current best practices (current year) on:

- Python packaging: is `setuptools` still the best choice or is `hatch`, `uv`, or `flit` better?
- Project layout: is `src/` layout still recommended?
- Logging: any better approaches than `logging` + `RotatingFileHandler`?
- CLI input/display: are `prompt_toolkit` + `rich` still the best combo or are there better alternatives?
- Building executables: is `pyinstaller` still the best choice or is `nuitka` or `briefcase` better?
- Version management: is `bump-my-version` still recommended?
- Linting: is `ruff` still the best choice?
- Cross-platform paths: is `platformdirs` still the standard?

Report your findings briefly and note any changes from the stack below before proceeding. If a clearly better alternative exists, recommend it and ask the user whether to use it.

---

## Phase 2 — Project Name

Chat with the user to determine the project name. Ask:

1. What does the tool do? (one sentence)
2. Who is the target user?
3. Any name ideas already?

Based on their answers, suggest 3-5 name options with short reasoning for each. Consider:
- Short and memorable
- Reflects the tool's purpose
- Available as a Python package name (check PyPI if possible)
- Works as a CLI command name (no spaces, no special chars)

Once the user picks a name, use it consistently everywhere as `<name>`.

---

## Phase 3 — Setup

Set up the following structure and files. Replace `<name>` with the chosen project name throughout.

### Directory structure

```
<name>/
├── .github/
│   ├── workflows/
│   │   ├── release.yaml
│   │   └── test.yaml
│   └── dependabot.yml
├── src/
│   └── <name>/
│       ├── __init__.py
│       ├── main.py
│       └── log.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── test_main.py
├── install.sh
├── install.ps1
├── .gitignore
├── README.md
└── pyproject.toml
```

---

### `pyproject.toml`

```toml
[build-system]
requires = ["setuptools >= 77.0.0"]
build-backend = "setuptools.build_meta"

[project]
name = "<name>"
dynamic = ["version"]
requires-python = ">=3.10"
dependencies = [
    "prompt_toolkit",
    "rich",
    "platformdirs",
]

[project.scripts]
<name> = "<name>.main:run"

[project.optional-dependencies]
build = ["pyinstaller"]
test = ["pytest", "ruff"]
dev = ["bump-my-version", "ruff"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.dynamic]
version = {attr = "<name>.__version__"}

[tool.bumpversion]
current_version = "0.1.0"
commit = true
tag = true
tag_name = "v{new_version}"

[[tool.bumpversion.files]]
filename = "src/<name>/__init__.py"
search = '__version__ = "{current_version}"'
replace = '__version__ = "{new_version}"'

[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I"]
```

---

### `src/<name>/__init__.py`

```python
__version__ = "0.1.0"
```

---

### `src/<name>/log.py`

```python
import logging
import logging.handlers
from pathlib import Path

from platformdirs import user_log_dir


def setup(
    console_level: str = "WARNING",
    file_level: str = "DEBUG",
    log_path: str = str(Path(user_log_dir("<name>", appauthor=False)) / "<name>.log"),
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, console_level.upper(), logging.WARNING))
    console.setFormatter(formatter)

    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    file = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    file.setLevel(getattr(logging, file_level.upper(), logging.DEBUG))
    file.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(file)

    return console, file
```

---

### `src/<name>/main.py`

```python
import argparse
import logging

from <name>.log import setup

logger = logging.getLogger(__name__)

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="WARNING", choices=LEVELS,
                        help="Console log level")
    parser.add_argument("--log-file", default="DEBUG", choices=LEVELS,
                        help="File log level")
    parser.add_argument("--log-path", default=None,
                        help="Path to log file")
    args = parser.parse_args()

    kwargs = {"console_level": args.log, "file_level": args.log_file}
    if args.log_path:
        kwargs["log_path"] = args.log_path

    setup(**kwargs)
    logger.info("%s started", "<name>")


if __name__ == "__main__":
    run()
```

---

### `tests/conftest.py`

```python
import logging


def pytest_configure(config):
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
```

---

### `tests/test_main.py`

```python
import argparse
import logging

import pytest

from <name>.log import setup


@pytest.fixture(autouse=True)
def clean_root_logger():
    """Isolate root logger handlers for each test."""
    root = logging.getLogger()
    original = list(root.handlers)
    root.handlers.clear()
    yield
    root.handlers.clear()
    root.handlers.extend(original)


# --- logging setup ---


def test_root_logger_set_to_debug(tmp_path):
    setup(log_path=str(tmp_path / "<name>.log"))
    assert logging.getLogger().level == logging.DEBUG


def test_console_handler_level(tmp_path):
    console, _ = setup(console_level="INFO", log_path=str(tmp_path / "<name>.log"))
    assert console.level == logging.INFO


def test_file_handler_level(tmp_path):
    _, file = setup(file_level="WARNING", log_path=str(tmp_path / "<name>.log"))
    assert file.level == logging.WARNING


def test_log_file_created(tmp_path):
    log_path = tmp_path / "<name>.log"
    setup(log_path=str(log_path))
    assert log_path.exists()


def test_log_directory_created(tmp_path):
    log_path = tmp_path / "subdir" / "<name>.log"
    setup(log_path=str(log_path))
    assert log_path.parent.exists()


def test_two_handlers_attached(tmp_path):
    handlers = setup(log_path=str(tmp_path / "<name>.log"))
    assert len(handlers) == 2


# --- CLI argument parsing ---


def make_parser():
    from <name>.main import LEVELS

    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="WARNING", choices=LEVELS)
    parser.add_argument("--log-file", default="DEBUG", choices=LEVELS)
    parser.add_argument("--log-path", default=None)
    return parser


def test_default_console_level():
    args = make_parser().parse_args([])
    assert args.log == "WARNING"


def test_default_file_level():
    args = make_parser().parse_args([])
    assert args.log_file == "DEBUG"


def test_default_log_path():
    args = make_parser().parse_args([])
    assert args.log_path is None


def test_custom_console_level():
    args = make_parser().parse_args(["--log", "DEBUG"])
    assert args.log == "DEBUG"


def test_custom_file_level():
    args = make_parser().parse_args(["--log-file", "ERROR"])
    assert args.log_file == "ERROR"


def test_custom_log_path():
    args = make_parser().parse_args(["--log-path", "/tmp/custom.log"])
    assert args.log_path == "/tmp/custom.log"


def test_invalid_level_rejected():
    with pytest.raises(SystemExit):
        make_parser().parse_args(["--log", "VERBOSE"])
```

---

### `.github/workflows/test.yaml`

```yaml
name: Test

on:
  push:
    branches: ["main"]
  pull_request:
    branches: ["main"]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: pip install -e ".[test]"

      - name: Lint
        run: ruff check .

      - name: Format check
        run: ruff format --check .

      - name: Run tests
        run: pytest
```

---

### `install.sh`

One-liner installer for Linux and macOS. Downloads the correct binary from the
latest GitHub release and places it in `~/.local/bin`.

```bash
#!/usr/bin/env bash
# install.sh — download and install <name> from the latest GitHub release.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<name>/main/install.sh | bash
#   INSTALL_DIR=/usr/local/bin bash install.sh   # custom location (needs sudo)
set -euo pipefail

REPO="<owner>/<name>"
BIN_NAME="<name>"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"

# ── Detect platform ──────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
  Linux)  PLATFORM="linux"  ;;
  Darwin) PLATFORM="macos"  ;;
  *)
    echo "Unsupported OS: $OS" >&2
    exit 1
    ;;
esac

# ── Resolve latest release tag ───────────────────────────────────────────────
echo "Fetching latest release info..."
TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
  | grep '"tag_name"' | head -1 \
  | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')"

if [ -z "$TAG" ]; then
  echo "Could not determine latest release tag." >&2
  exit 1
fi

# ── Download binary ──────────────────────────────────────────────────────────
URL="https://github.com/$REPO/releases/download/$TAG/${BIN_NAME}-${TAG}-${PLATFORM}"
echo "Downloading $BIN_NAME $TAG ($PLATFORM)..."

mkdir -p "$INSTALL_DIR"
curl -fsSL "$URL" -o "$INSTALL_DIR/$BIN_NAME"
chmod +x "$INSTALL_DIR/$BIN_NAME"

echo "Installed to $INSTALL_DIR/$BIN_NAME"

# ── PATH hint ────────────────────────────────────────────────────────────────
if ! echo ":$PATH:" | grep -q ":$INSTALL_DIR:"; then
  echo ""
  echo "  $INSTALL_DIR is not in your PATH."
  echo "  Add it by running:"
  echo ""
  echo "    echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> ~/.bashrc  # bash"
  echo "    echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> ~/.zshrc   # zsh"
  echo ""
  echo "  Then restart your terminal."
fi

echo "Done. Run: $BIN_NAME"
```

---

### `install.ps1`

One-liner installer for Windows. Downloads the binary from the latest GitHub
release, places it in `%LOCALAPPDATA%\Programs\<name>`, and adds that directory
to the user `PATH`.

```powershell
# install.ps1 — download and install <name> from the latest GitHub release.
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/<owner>/<name>/main/install.ps1 | iex
#   # or with a custom install location:
#   $env:INSTALL_DIR = "C:\Tools"; irm .../install.ps1 | iex
param(
    [string]$InstallDir = $env:INSTALL_DIR
)

$ErrorActionPreference = "Stop"

$Repo    = "<owner>/<name>"
$BinName = "<name>"

if (-not $InstallDir) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\$BinName"
}

# ── Resolve latest release tag ───────────────────────────────────────────────
Write-Host "Fetching latest release info..."
$Release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest"
$Tag     = $Release.tag_name

# ── Download binary ──────────────────────────────────────────────────────────
$Url  = "https://github.com/$Repo/releases/download/$Tag/${BinName}-${Tag}-windows.exe"
$Dest = Join-Path $InstallDir "$BinName.exe"

Write-Host "Downloading $BinName $Tag..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Invoke-WebRequest -Uri $Url -OutFile $Dest

Write-Host "Installed to $Dest"

# ── Add to user PATH if not already present ──────────────────────────────────
$UserPath = [Environment]::GetEnvironmentVariable("PATH", "User") ?? ""
if ($UserPath -notlike "*$InstallDir*") {
    $NewPath = ($UserPath.TrimEnd(";") + ";$InstallDir").TrimStart(";")
    [Environment]::SetEnvironmentVariable("PATH", $NewPath, "User")
    Write-Host "Added $InstallDir to user PATH (restart your terminal to take effect)"
}

Write-Host "Done. Run: $BinName"
```

---

### `.github/workflows/release.yaml`

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

jobs:
  build:
    strategy:
      matrix:
        os: [windows-latest, ubuntu-latest, macos-latest]
    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: pip install ".[build]"

      - name: Build executable
        run: pyinstaller --onefile --console --name <name> src/<name>/main.py

      - name: Rename executable
        shell: bash
        run: |
          if [ -f dist/<name>.exe ]; then
            mv dist/<name>.exe "dist/<name>-${{ github.ref_name }}-windows.exe"
          else
            mv dist/<name> "dist/<name>-${{ github.ref_name }}-$(uname -s | tr '[:upper:]' '[:lower:]')"
          fi

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: <name>_${{ github.ref_name }}_${{ matrix.os }}
          path: dist/<name>-${{ github.ref_name }}-*

  release:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/download-artifact@v4
        with:
          path: dist/

      - uses: softprops/action-gh-release@v2
        with:
          files: dist/**/*
```

---

### `.github/dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

---

### `.gitignore`

```
# build artifacts
dist/
build/

# Python cache (all locations)
**/__pycache__/
*.pyc
*.pyo

# logs (any location)
*.log

# pytest
.pytest_cache/

# editor
.vscode/
.idea/

*egg-info/

.claude
.venv
```

---

### `README.md`

````markdown
# <name>

A short description of what the tool does.

## Installation

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<name>/main/install.sh | bash
```

Installs to `~/.local/bin`. Override with `INSTALL_DIR=/usr/local/bin bash install.sh`.

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/<owner>/<name>/main/install.ps1 | iex
```

Installs to `%LOCALAPPDATA%\Programs\<name>` and adds it to the user `PATH`.

### From source

```bash
pip install -e .
```

## Usage

```bash
<name> [OPTIONS]
```

## Options

| Flag | Default | Description |
|---|---|---|
| `--log` | `WARNING` | Console log level |
| `--log-file` | `DEBUG` | File log level |
| `--log-path` | platform default | Path to log file |

**Log levels:** `DEBUG`, `INFO`, `WARNING`, `ERROR`

## Examples

```bash
<name>                                     # console: WARNING+, file: DEBUG+
<name> --log DEBUG                         # verbose console output
<name> --log INFO --log-file WARNING       # custom levels
<name> --log-path ./logs/<name>.log        # custom log file location
```

## Log file location

By default logs are written to the platform-appropriate user directory:

- **Windows:** `%LOCALAPPDATA%\<name>\Logs\<name>.log`
- **macOS:** `~/Library/Logs/<name>/<name>.log`
- **Linux:** `~/.cache/<name>/log/<name>.log`

## Development

```bash
pip install -e ".[test]"    # install with test dependencies
pip install -e ".[dev]"     # install with dev dependencies
pytest                      # run tests
ruff check .                # lint
ruff format .               # format code
```

## Releasing

```bash
bump-my-version bump patch   # 0.1.0 → 0.1.1
bump-my-version bump minor   # 0.1.1 → 0.2.0
bump-my-version bump major   # 0.2.0 → 1.0.0
git push --follow-tags       # triggers release workflow
```

## CI/CD

- **test.yaml** — runs ruff and pytest on every push/PR to `main`
- **release.yaml** — builds standalone executables for Windows, Linux, and macOS on version tag push and attaches them to the GitHub release
- **install.sh / install.ps1** — one-liner installers that fetch the correct binary from the latest release and add it to `PATH`
- **Dependabot** — opens weekly PRs to update pip and GitHub Actions dependencies
````

---

## Phase 4 — Verify

After writing all files:

1. Run `pip install -e ".[test]"` and confirm it succeeds
2. Run `pytest` and confirm all tests pass
3. Run `ruff check .` and confirm no issues
4. Run `ruff format --check .` and confirm no issues
5. Remind the user to replace `<owner>` in `install.sh`, `install.ps1`, and `README.md` with their GitHub username/org
6. Report any failures and fix them before finishing
