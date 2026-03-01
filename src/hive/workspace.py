import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_HIVE_DIR = ".hive"


@dataclass
class Session:
    id: str
    path: Path
    meta: dict

    @property
    def history_path(self) -> Path:
        return self.path / "history"

    @property
    def output_path(self) -> Path:
        return self.path / "output"

    @property
    def log_path(self) -> Path:
        return self.path / "hive.log"

    @property
    def started(self) -> str:
        return self.meta.get("started", "")


def _hive_path(cwd: Path) -> Path:
    return cwd / _HIVE_DIR


def is_trusted(cwd: Path) -> bool:
    """Return True if a .hive/ workspace exists in cwd."""
    return _hive_path(cwd).is_dir()


def create_workspace(cwd: Path) -> Path:
    """Create the .hive/ directory and return its path."""
    path = _hive_path(cwd)
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_session(cwd: Path) -> Session:
    """Create a new session directory with meta.json and return a Session."""
    session_id = secrets.token_hex(3)
    session_path = _hive_path(cwd) / session_id
    session_path.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": session_id,
        "started": datetime.now().isoformat(),
        "cwd": str(cwd),
    }
    (session_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return Session(id=session_id, path=session_path, meta=meta)


def get_session(cwd: Path, session_id: str) -> "Session | None":
    """Return the Session with the given ID, or None if not found."""
    session_path = _hive_path(cwd) / session_id
    meta_file = session_path / "meta.json"
    if not meta_file.exists():
        return None
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    return Session(id=session_id, path=session_path, meta=meta)


def list_sessions(cwd: Path) -> "list[Session]":
    """Return all sessions sorted by started timestamp ascending."""
    hive = _hive_path(cwd)
    if not hive.is_dir():
        return []
    sessions = []
    for entry in hive.iterdir():
        if entry.is_dir():
            meta_file = entry / "meta.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                sessions.append(Session(id=entry.name, path=entry, meta=meta))
    sessions.sort(key=lambda s: s.started)
    return sessions


def get_config(cwd: Path) -> dict:
    """Read .hive/config.json, returning {} if missing."""
    config_path = _hive_path(cwd) / "config.json"
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def save_config(cwd: Path, config: dict) -> None:
    """Write .hive/config.json."""
    config_path = _hive_path(cwd) / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")


def has_language(cwd: Path) -> bool:
    """Return True only if a language has been explicitly configured."""
    return "language" in get_config(cwd)


def get_language(cwd: Path) -> "str | None":
    """Return the configured language code, or None if not set."""
    return get_config(cwd).get("language")


def set_language(cwd: Path, lang: str) -> None:
    """Persist the language choice to .hive/config.json."""
    config = get_config(cwd)
    config["language"] = lang
    save_config(cwd, config)


def get_model(cwd: Path) -> "str | None":
    """Return the configured AI model, or None if not set."""
    return get_config(cwd).get("model")


def set_model(cwd: Path, model: str) -> None:
    """Persist the AI model choice to .hive/config.json."""
    config = get_config(cwd)
    config["model"] = model
    save_config(cwd, config)


def save_output(session: Session, lines: list[str]) -> None:
    """Write output lines as JSON-lines to the session output file."""
    session.output_path.write_text(
        "\n".join(json.dumps(line) for line in lines),
        encoding="utf-8",
    )


def load_output(session: Session) -> list[str]:
    """Load output lines from the session output file."""
    if not session.output_path.exists():
        return []
    result = []
    for line in session.output_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return result
