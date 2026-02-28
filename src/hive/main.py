import argparse
import logging
from pathlib import Path

from hive.log import setup

logger = logging.getLogger(__name__)

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--log", default="WARNING", choices=LEVELS, help="Console log level"
    )
    parser.add_argument(
        "--log-file", default="DEBUG", choices=LEVELS, help="File log level"
    )
    parser.add_argument("--log-path", default=None, help="Path to log file")
    parser.add_argument(
        "--resume", default=None, metavar="ID", help="Resume a session by ID"
    )
    parser.add_argument(
        "--list-sessions", action="store_true", help="Print sessions and exit"
    )
    args = parser.parse_args()

    cwd = Path.cwd()

    if args.list_sessions:
        _cmd_list_sessions(cwd)
        return

    session = None
    trusted = False

    if args.resume:
        from hive.workspace import get_session, is_trusted

        if not is_trusted(cwd):
            print(f"No .hive workspace found in {cwd}")
            return
        session = get_session(cwd, args.resume)
        if session is None:
            print(f"Session '{args.resume}' not found in {cwd}")
            return
        trusted = True
    else:
        from hive.workspace import is_trusted

        trusted = is_trusted(cwd)

    kwargs = {"console_level": args.log, "file_level": args.log_file}
    if args.log_path:
        kwargs["log_path"] = args.log_path

    setup(**kwargs)

    logger.info("Hive started")

    from hive.ui.app import HiveApp

    HiveApp(cwd=cwd, session=session, trusted=trusted).run()


def _cmd_list_sessions(cwd: Path) -> None:
    from hive.workspace import list_sessions

    sessions = list_sessions(cwd)
    if not sessions:
        print(f"No sessions in {cwd}")
        return

    print(f"Sessions in {cwd}:")
    for s in sessions:
        cmd_count = 0
        if s.history_path.exists():
            lines = [
                ln
                for ln in s.history_path.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            cmd_count = len(lines)
        print(f"  {s.id}  {s.started}  {cmd_count:2d} commands")


if __name__ == "__main__":
    run()
