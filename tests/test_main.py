import argparse
import logging

import pytest

from hive.log import setup


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
    setup(log_path=str(tmp_path / "hive.log"))
    assert logging.getLogger().level == logging.DEBUG


def test_console_handler_level(tmp_path):
    console, _ = setup(console_level="INFO", log_path=str(tmp_path / "hive.log"))
    assert console.level == logging.INFO


def test_file_handler_level(tmp_path):
    _, file = setup(file_level="WARNING", log_path=str(tmp_path / "hive.log"))
    assert file.level == logging.WARNING


def test_log_file_created(tmp_path):
    log_path = tmp_path / "hive.log"
    setup(log_path=str(log_path))
    assert log_path.exists()


def test_log_directory_created(tmp_path):
    log_path = tmp_path / "subdir" / "hive.log"
    setup(log_path=str(log_path))
    assert log_path.parent.exists()


def test_two_handlers_attached(tmp_path):
    handlers = setup(log_path=str(tmp_path / "hive.log"))
    assert len(handlers) == 2


# --- CLI argument parsing ---


def make_parser():
    from hive.main import LEVELS

    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="WARNING", choices=LEVELS)
    parser.add_argument("--log-file", default="DEBUG", choices=LEVELS)
    parser.add_argument("--log-path", default=None)
    parser.add_argument("--session", default=None, metavar="ID")
    parser.add_argument("--list-sessions", action="store_true")
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


def test_default_session():
    args = make_parser().parse_args([])
    assert args.session is None


def test_session_arg():
    args = make_parser().parse_args(["--session", "a3f9b2"])
    assert args.session == "a3f9b2"


def test_list_sessions_default_false():
    args = make_parser().parse_args([])
    assert args.list_sessions is False


def test_list_sessions_flag():
    args = make_parser().parse_args(["--list-sessions"])
    assert args.list_sessions is True


# --- _cmd_list_sessions ---


def test_cmd_list_sessions_no_workspace(tmp_path, capsys):
    from hive.main import _cmd_list_sessions

    _cmd_list_sessions(tmp_path)
    out = capsys.readouterr().out
    assert "No sessions" in out


def test_cmd_list_sessions_shows_sessions(tmp_path, capsys):
    from hive.main import _cmd_list_sessions
    from hive.workspace import create_workspace, new_session

    create_workspace(tmp_path)
    s = new_session(tmp_path)
    _cmd_list_sessions(tmp_path)
    out = capsys.readouterr().out
    assert s.id in out
    assert "Sessions in" in out


def test_cmd_list_sessions_shows_command_count(tmp_path, capsys):
    import json as _json

    from hive.main import _cmd_list_sessions
    from hive.workspace import create_workspace, new_session

    create_workspace(tmp_path)
    s = new_session(tmp_path)
    s.history_path.write_text(
        "\n".join(_json.dumps(e) for e in ["cmd1", "cmd2"]), encoding="utf-8"
    )
    _cmd_list_sessions(tmp_path)
    out = capsys.readouterr().out
    assert "2" in out
