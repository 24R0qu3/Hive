"""Global user configuration (name, preferences) stored in the platform config dir."""

from __future__ import annotations

import json
from pathlib import Path

from platformdirs import user_config_dir


def _get_config_dir() -> Path:
    return Path(user_config_dir("hive", appauthor=False))


def _get_user_file() -> Path:
    return _get_config_dir() / "user.json"


def _read() -> dict:
    user_file = _get_user_file()
    if not user_file.exists():
        return {}
    return json.loads(user_file.read_text(encoding="utf-8"))


def _write(config: dict) -> None:
    user_file = _get_user_file()
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text(json.dumps(config), encoding="utf-8")


def get_user_name() -> str | None:
    """Return the stored user name, or None if not set."""
    return _read().get("name")


def has_user_name() -> bool:
    """Return True if a user name has been stored."""
    return "name" in _read()


def set_user_name(name: str) -> None:
    """Persist the user name to the global config file."""
    config = _read()
    config["name"] = name
    _write(config)
