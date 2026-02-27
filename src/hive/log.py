import logging
import logging.handlers
from pathlib import Path

from platformdirs import user_log_dir


def setup(
    console_level: str = "WARNING",
    file_level: str = "DEBUG",
    log_path: str = str(Path(user_log_dir("hive", appauthor=False)) / "hive.log"),
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # let handlers filter, not the root

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # --- console handler ---
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, console_level.upper(), logging.WARNING))
    console.setFormatter(formatter)

    # --- file handler ---
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
