import json
import logging

import pytest

from hive.workspace import (
    create_workspace,
    get_session,
    is_trusted,
    list_sessions,
    load_output,
    new_session,
    save_output,
)

# ---------------------------------------------------------------------------
# is_trusted
# ---------------------------------------------------------------------------


def test_not_trusted_when_no_hive(tmp_path):
    assert is_trusted(tmp_path) is False


def test_trusted_when_hive_dir_exists(tmp_path):
    (tmp_path / ".hive").mkdir()
    assert is_trusted(tmp_path) is True


def test_not_trusted_when_hive_is_file(tmp_path):
    (tmp_path / ".hive").write_text("not a dir")
    assert is_trusted(tmp_path) is False


# ---------------------------------------------------------------------------
# create_workspace
# ---------------------------------------------------------------------------


def test_create_workspace_makes_hive_dir(tmp_path):
    path = create_workspace(tmp_path)
    assert path.is_dir()
    assert path == tmp_path / ".hive"


def test_create_workspace_idempotent(tmp_path):
    create_workspace(tmp_path)
    create_workspace(tmp_path)  # should not raise
    assert (tmp_path / ".hive").is_dir()


# ---------------------------------------------------------------------------
# new_session
# ---------------------------------------------------------------------------


def test_new_session_creates_directory(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert session.path.is_dir()


def test_new_session_creates_meta_json(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert session.path.joinpath("meta.json").exists()


def test_new_session_meta_has_required_fields(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert "id" in session.meta
    assert "started" in session.meta
    assert "cwd" in session.meta


def test_new_session_id_is_six_hex_chars(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert len(session.id) == 6
    assert all(c in "0123456789abcdef" for c in session.id)


def test_new_session_cwd_in_meta(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert session.meta["cwd"] == str(tmp_path)


def test_new_session_unique_ids(tmp_path):
    create_workspace(tmp_path)
    s1 = new_session(tmp_path)
    s2 = new_session(tmp_path)
    assert s1.id != s2.id


# ---------------------------------------------------------------------------
# Session properties
# ---------------------------------------------------------------------------


def test_session_history_path(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert session.history_path == session.path / "history"


def test_session_output_path(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert session.output_path == session.path / "output"


def test_session_log_path(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert session.log_path == session.path / "hive.log"


def test_session_started_matches_meta(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert session.started == session.meta["started"]


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------


def test_get_session_returns_session(tmp_path):
    create_workspace(tmp_path)
    created = new_session(tmp_path)
    found = get_session(tmp_path, created.id)
    assert found is not None
    assert found.id == created.id


def test_get_session_returns_none_for_missing_id(tmp_path):
    create_workspace(tmp_path)
    assert get_session(tmp_path, "ffffff") is None


def test_get_session_none_when_no_workspace(tmp_path):
    assert get_session(tmp_path, "aaaaaa") is None


def test_get_session_meta_matches(tmp_path):
    create_workspace(tmp_path)
    created = new_session(tmp_path)
    found = get_session(tmp_path, created.id)
    assert found.meta["started"] == created.meta["started"]


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


def test_list_sessions_empty_when_no_workspace(tmp_path):
    assert list_sessions(tmp_path) == []


def test_list_sessions_empty_when_no_sessions(tmp_path):
    create_workspace(tmp_path)
    assert list_sessions(tmp_path) == []


def test_list_sessions_returns_all_sessions(tmp_path):
    create_workspace(tmp_path)
    s1 = new_session(tmp_path)
    s2 = new_session(tmp_path)
    sessions = list_sessions(tmp_path)
    ids = {s.id for s in sessions}
    assert s1.id in ids
    assert s2.id in ids


def test_list_sessions_sorted_by_started(tmp_path):
    create_workspace(tmp_path)
    # Create sessions and manipulate their started timestamps to force a known order
    s1 = new_session(tmp_path)
    s2 = new_session(tmp_path)
    # Overwrite meta to give s2 an earlier timestamp
    meta1 = s1.meta.copy()
    meta2 = s2.meta.copy()
    meta1["started"] = "2026-02-28T10:00:00"
    meta2["started"] = "2026-02-28T09:00:00"
    (s1.path / "meta.json").write_text(json.dumps(meta1), encoding="utf-8")
    (s2.path / "meta.json").write_text(json.dumps(meta2), encoding="utf-8")
    sessions = list_sessions(tmp_path)
    assert sessions[0].id == s2.id
    assert sessions[1].id == s1.id


def test_list_sessions_ignores_non_session_dirs(tmp_path):
    create_workspace(tmp_path)
    # A dir without meta.json should be ignored
    (tmp_path / ".hive" / "garbage").mkdir()
    assert list_sessions(tmp_path) == []


# ---------------------------------------------------------------------------
# save_output / load_output
# ---------------------------------------------------------------------------


def test_save_and_load_output_roundtrip(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    lines = ["hello", "\x1b[32mworld\x1b[0m", ""]
    save_output(session, lines)
    assert load_output(session) == lines


def test_load_output_empty_when_file_missing(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert load_output(session) == []


def test_save_output_creates_file(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    save_output(session, ["line"])
    assert session.output_path.exists()


def test_load_output_skips_blank_lines(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    session.output_path.write_text(
        json.dumps("a") + "\n\n" + json.dumps("b") + "\n",
        encoding="utf-8",
    )
    assert load_output(session) == ["a", "b"]


# ---------------------------------------------------------------------------
# add_session_handler (log.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_root_logger():
    root = logging.getLogger()
    original = list(root.handlers)
    root.handlers.clear()
    yield
    # Close any FileHandlers added during the test to release file locks
    for h in root.handlers:
        h.close()
    root.handlers.clear()
    root.handlers.extend(original)


def test_add_session_handler_attaches_handler(tmp_path):
    from hive.log import add_session_handler

    log_path = tmp_path / "session.log"
    handler = add_session_handler(str(log_path))
    assert handler in logging.getLogger().handlers


def test_add_session_handler_creates_log_file(tmp_path):
    from hive.log import add_session_handler

    log_path = tmp_path / "subdir" / "session.log"
    add_session_handler(str(log_path))
    logging.getLogger().info("test")
    assert log_path.exists()


def test_add_session_handler_default_level(tmp_path):
    from hive.log import add_session_handler

    handler = add_session_handler(str(tmp_path / "s.log"))
    assert handler.level == logging.DEBUG


def test_add_session_handler_custom_level(tmp_path):
    from hive.log import add_session_handler

    handler = add_session_handler(str(tmp_path / "s.log"), file_level="WARNING")
    assert handler.level == logging.WARNING


def test_add_session_handler_is_file_handler(tmp_path):
    from hive.log import add_session_handler

    handler = add_session_handler(str(tmp_path / "s.log"))
    assert isinstance(handler, logging.FileHandler)
