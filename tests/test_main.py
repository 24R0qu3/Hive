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
    parser.add_argument("--log-path", default="hive.log")
    return parser


def test_default_console_level():
    args = make_parser().parse_args([])
    assert args.log == "WARNING"


def test_default_file_level():
    args = make_parser().parse_args([])
    assert args.log_file == "DEBUG"


def test_default_log_path():
    args = make_parser().parse_args([])
    assert args.log_path == "hive.log"


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
