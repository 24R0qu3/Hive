# Hive

An interactive CLI tool built with `prompt_toolkit` and `rich`.

## Installation

```bash
pip install -e .
```

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

**Log levels:** `DEBUG`, `INFO`, `WARNING`, `ERROR`

## Examples

```bash
hive                                      # console: WARNING+, file: DEBUG+
hive --log DEBUG                          # verbose console output
hive --log INFO --log-file WARNING        # custom levels
hive --log-path ./logs/hive.log          # custom log file location
```

## Log file location

By default logs are written to the platform-appropriate user directory:

- **Windows:** `%LOCALAPPDATA%\hive\Logs\hive.log`
- **macOS:** `~/Library/Logs/hive/hive.log`
- **Linux:** `~/.cache/hive/log/hive.log`

## Development

```bash
pip install -e ".[test]"   # install with test dependencies
pytest                     # run tests
```
