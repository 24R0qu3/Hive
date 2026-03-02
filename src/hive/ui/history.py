"""History management for Hive sessions."""
from __future__ import annotations

import json
from pathlib import Path


def load_history_file(path: Path) -> list[str]:
    """Load command history from a JSON-lines file.

    Also migrates the legacy prompt_toolkit FileHistory format
    (lines prefixed with '+', timestamps prefixed with '#').
    """
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            if line.startswith("+"):
                entries.append(line[1:])
    return entries


class HistoryManager:
    """Manages command history for a session: load, save, and navigate."""

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path | None = path
        self._entries: list[str] = []
        self._idx: int = 0
        self._draft: str = ""
        if path is not None:
            self._load()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path | None:
        return self._path

    @path.setter
    def path(self, value: Path | None) -> None:
        self._path = value
        self._draft = ""
        if value is not None:
            self._load()
        else:
            self._entries = []
            self._idx = 0

    @property
    def entries(self) -> list[str]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def _load(self) -> None:
        assert self._path is not None
        self._entries = load_history_file(self._path)
        self._idx = len(self._entries)
        self._draft = ""

    def _save(self) -> None:
        if self._path is not None:
            self._path.write_text(
                "\n".join(json.dumps(e) for e in self._entries),
                encoding="utf-8",
            )

    def append(self, text: str) -> None:
        """Add an entry, reset navigation to the live position, and save."""
        self._entries.append(text)
        self._idx = len(self._entries)
        self._draft = ""
        self._save()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate_back(self, current_text: str) -> str | None:
        """Navigate to the previous entry.

        Saves *current_text* as the draft if we are at the live position.
        Returns the entry text, or None if already at the first entry.
        """
        if not self._entries:
            return None
        if self._idx == len(self._entries):
            self._draft = current_text
        if self._idx > 0:
            self._idx -= 1
            return self._entries[self._idx]
        return None

    def navigate_forward(self) -> str | None:
        """Navigate to the next (more recent) entry.

        Returns the entry text, the draft when moving past the last entry,
        or None if already at the live position.
        """
        if self._idx < len(self._entries) - 1:
            self._idx += 1
            return self._entries[self._idx]
        if self._idx == len(self._entries) - 1:
            self._idx = len(self._entries)
            return self._draft
        return None
