import json
import logging

import pytest

from hive.workspace import (
    DEFAULT_SUMMARIZATION_TOKEN_LIMIT,
    _dump_agent_md,
    _parse_agent_md,
    create_workspace,
    delete_agent_config,
    get_agent_configs,
    get_config,
    get_language,
    get_model,
    get_session,
    get_summarization_token_limit,
    has_language,
    is_trusted,
    list_sessions,
    load_conversation,
    load_full_conversation,
    load_output,
    new_session,
    save_agent_config,
    save_config,
    save_conversation,
    save_full_conversation,
    save_output,
    set_language,
    set_model,
    set_summarization_token_limit,
    update_meta,
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


def test_session_conversation_path(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert session.conversation_path == session.path / "conversation.json"


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


# ---------------------------------------------------------------------------
# get_config / save_config
# ---------------------------------------------------------------------------


def test_get_config_returns_empty_dict_when_no_file(tmp_path):
    create_workspace(tmp_path)
    assert get_config(tmp_path) == {}


def test_get_config_returns_empty_dict_when_no_workspace(tmp_path):
    assert get_config(tmp_path) == {}


def test_save_and_get_config_roundtrip(tmp_path):
    create_workspace(tmp_path)
    save_config(tmp_path, {"foo": "bar", "num": 42})
    assert get_config(tmp_path) == {"foo": "bar", "num": 42}


def test_save_config_overwrites_previous(tmp_path):
    create_workspace(tmp_path)
    save_config(tmp_path, {"a": 1})
    save_config(tmp_path, {"b": 2})
    assert get_config(tmp_path) == {"b": 2}


def test_save_config_creates_file(tmp_path):
    create_workspace(tmp_path)
    save_config(tmp_path, {"x": "y"})
    assert (tmp_path / ".hive" / "config.json").exists()


# ---------------------------------------------------------------------------
# has_language / get_language / set_language
# ---------------------------------------------------------------------------


def test_has_language_false_when_no_config(tmp_path):
    create_workspace(tmp_path)
    assert has_language(tmp_path) is False


def test_has_language_false_when_key_missing(tmp_path):
    create_workspace(tmp_path)
    save_config(tmp_path, {"other": "value"})
    assert has_language(tmp_path) is False


def test_has_language_true_after_set(tmp_path):
    create_workspace(tmp_path)
    set_language(tmp_path, "en")
    assert has_language(tmp_path) is True


def test_get_language_none_when_not_set(tmp_path):
    create_workspace(tmp_path)
    assert get_language(tmp_path) is None


def test_get_language_none_when_no_workspace(tmp_path):
    assert get_language(tmp_path) is None


def test_set_language_persists(tmp_path):
    create_workspace(tmp_path)
    set_language(tmp_path, "de")
    assert get_language(tmp_path) == "de"


def test_set_language_overwrites(tmp_path):
    create_workspace(tmp_path)
    set_language(tmp_path, "en")
    set_language(tmp_path, "de")
    assert get_language(tmp_path) == "de"


def test_set_language_preserves_other_config_keys(tmp_path):
    create_workspace(tmp_path)
    save_config(tmp_path, {"other": "keep"})
    set_language(tmp_path, "en")
    assert get_config(tmp_path)["other"] == "keep"
    assert get_config(tmp_path)["language"] == "en"


# ---------------------------------------------------------------------------
# get_model / set_model
# ---------------------------------------------------------------------------


def test_get_model_none_when_not_set(tmp_path):
    create_workspace(tmp_path)
    assert get_model(tmp_path) is None


def test_get_model_none_when_no_workspace(tmp_path):
    assert get_model(tmp_path) is None


def test_set_model_persists(tmp_path):
    create_workspace(tmp_path)
    set_model(tmp_path, "llama3.2")
    assert get_model(tmp_path) == "llama3.2"


def test_set_model_overwrites(tmp_path):
    create_workspace(tmp_path)
    set_model(tmp_path, "llama3.2")
    set_model(tmp_path, "mistral")
    assert get_model(tmp_path) == "mistral"


def test_set_model_preserves_other_config_keys(tmp_path):
    create_workspace(tmp_path)
    save_config(tmp_path, {"language": "en"})
    set_model(tmp_path, "llama3.2")
    assert get_config(tmp_path)["language"] == "en"
    assert get_config(tmp_path)["model"] == "llama3.2"


# ---------------------------------------------------------------------------
# save_conversation / load_conversation
# ---------------------------------------------------------------------------


def test_session_conversation_path_property(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert session.conversation_path == session.path / "conversation.json"


def test_save_and_load_conversation_roundtrip(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    conversation = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    save_conversation(session, conversation)
    assert load_conversation(session) == conversation


def test_load_conversation_empty_when_no_file(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    assert load_conversation(session) == []


def test_save_conversation_creates_file(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    save_conversation(session, [{"role": "user", "content": "test"}])
    assert session.conversation_path.exists()


def test_load_conversation_empty_on_malformed_json(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    session.conversation_path.write_text("not valid json", encoding="utf-8")
    assert load_conversation(session) == []


def test_load_conversation_empty_when_not_a_list(tmp_path):
    """A JSON object (not an array) should be treated as malformed."""
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    session.conversation_path.write_text('{"role": "user"}', encoding="utf-8")
    assert load_conversation(session) == []


def test_save_conversation_preserves_unicode(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    msgs = [{"role": "user", "content": "Héllo wörld 🐝"}]
    save_conversation(session, msgs)
    assert load_conversation(session) == msgs


def test_save_conversation_overwrites_previous(tmp_path):
    create_workspace(tmp_path)
    session = new_session(tmp_path)
    save_conversation(session, [{"role": "user", "content": "first"}])
    save_conversation(session, [{"role": "user", "content": "second"}])
    result = load_conversation(session)
    assert len(result) == 1
    assert result[0]["content"] == "second"


# ---------------------------------------------------------------------------
# full_conversation
# ---------------------------------------------------------------------------


def test_session_full_conversation_path_property(tmp_path):
    session = new_session(tmp_path)
    assert session.full_conversation_path == session.path / "full_conversation.json"


def test_save_and_load_full_conversation_roundtrip(tmp_path):
    session = new_session(tmp_path)
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    save_full_conversation(session, messages)
    assert load_full_conversation(session) == messages


def test_load_full_conversation_returns_empty_when_no_file(tmp_path):
    session = new_session(tmp_path)
    assert load_full_conversation(session) == []


def test_load_full_conversation_returns_empty_on_malformed_json(tmp_path):
    session = new_session(tmp_path)
    session.full_conversation_path.write_text("not json", encoding="utf-8")
    assert load_full_conversation(session) == []


# ---------------------------------------------------------------------------
# new_session meta fields / update_meta
# ---------------------------------------------------------------------------


def test_new_session_meta_has_ended_at_and_last_message(tmp_path):
    session = new_session(tmp_path)
    assert "ended_at" in session.meta
    assert session.meta["ended_at"] is None
    assert session.meta["last_message"] == ""


def test_update_meta_writes_fields(tmp_path):
    session = new_session(tmp_path)
    update_meta(session, "2026-01-01T12:00:00", "hello world")
    # reload meta
    meta = json.loads((session.path / "meta.json").read_text(encoding="utf-8"))
    assert meta["ended_at"] == "2026-01-01T12:00:00"
    assert meta["last_message"] == "hello world"


def test_update_meta_preserves_other_fields(tmp_path):
    session = new_session(tmp_path)
    original_id = session.id
    original_started = session.meta["started"]
    update_meta(session, "2026-01-01T12:00:00", "msg")
    meta = json.loads((session.path / "meta.json").read_text(encoding="utf-8"))
    assert meta["id"] == original_id
    assert meta["started"] == original_started


# ---------------------------------------------------------------------------
# get_summarization_token_limit / set_summarization_token_limit
# ---------------------------------------------------------------------------


def test_get_summarization_token_limit_default(tmp_path):
    assert get_summarization_token_limit(tmp_path) == DEFAULT_SUMMARIZATION_TOKEN_LIMIT


def test_set_and_get_summarization_token_limit(tmp_path):
    create_workspace(tmp_path)
    set_summarization_token_limit(tmp_path, 3000)
    assert get_summarization_token_limit(tmp_path) == 3000


# ---------------------------------------------------------------------------
# _parse_agent_md / _dump_agent_md
# ---------------------------------------------------------------------------

_SAMPLE_MD = """\
---
name: test-agent
description: A test agent
tools:
  - shell
max_steps: 5
stop_phrase: DONE
---

You are a test agent.
Say DONE when finished.
"""


def test_parse_agent_md_name(tmp_path):
    config = _parse_agent_md(_SAMPLE_MD)
    assert config["name"] == "test-agent"


def test_parse_agent_md_description(tmp_path):
    config = _parse_agent_md(_SAMPLE_MD)
    assert config["description"] == "A test agent"


def test_parse_agent_md_tools(tmp_path):
    config = _parse_agent_md(_SAMPLE_MD)
    assert config["tools"] == ["shell"]


def test_parse_agent_md_max_steps_is_int(tmp_path):
    config = _parse_agent_md(_SAMPLE_MD)
    assert config["max_steps"] == 5


def test_parse_agent_md_stop_phrase(tmp_path):
    config = _parse_agent_md(_SAMPLE_MD)
    assert config["stop_phrase"] == "DONE"


def test_parse_agent_md_system_prompt(tmp_path):
    config = _parse_agent_md(_SAMPLE_MD)
    assert "You are a test agent" in config["system_prompt"]


def test_parse_agent_md_no_tools_is_none(tmp_path):
    md = """\
---
name: x
description: y
tools:
max_steps: 10
stop_phrase: TASK_COMPLETE
---

prompt
"""
    config = _parse_agent_md(md)
    assert config["tools"] is None


def test_parse_agent_md_invalid_raises(tmp_path):
    with pytest.raises(ValueError):
        _parse_agent_md("no frontmatter here")


def test_dump_agent_md_round_trip(tmp_path):
    original = {
        "name": "round-trip",
        "description": "test",
        "tools": ["shell"],
        "max_steps": 7,
        "stop_phrase": "DONE",
        "system_prompt": "Be helpful.",
    }
    dumped = _dump_agent_md(original)
    parsed = _parse_agent_md(dumped)
    assert parsed["name"] == original["name"]
    assert parsed["description"] == original["description"]
    assert parsed["tools"] == original["tools"]
    assert parsed["max_steps"] == original["max_steps"]
    assert parsed["stop_phrase"] == original["stop_phrase"]
    assert "Be helpful." in parsed["system_prompt"]


def test_dump_agent_md_no_tools_round_trip(tmp_path):
    config = {
        "name": "no-tools",
        "description": "x",
        "tools": None,
        "max_steps": 10,
        "stop_phrase": "TASK_COMPLETE",
        "system_prompt": "Do stuff.",
    }
    dumped = _dump_agent_md(config)
    parsed = _parse_agent_md(dumped)
    assert parsed["tools"] is None


# ---------------------------------------------------------------------------
# save_agent_config / get_agent_configs / delete_agent_config (.md format)
# ---------------------------------------------------------------------------


def test_save_agent_config_creates_md_file(tmp_path):
    create_workspace(tmp_path)
    save_agent_config(
        tmp_path,
        {
            "name": "myagent",
            "description": "x",
            "tools": None,
            "max_steps": 10,
            "stop_phrase": "TASK_COMPLETE",
            "system_prompt": "Do stuff.",
        },
    )
    assert (tmp_path / ".hive" / "agents" / "myagent.md").exists()


def test_save_agent_config_does_not_create_json(tmp_path):
    create_workspace(tmp_path)
    save_agent_config(
        tmp_path,
        {
            "name": "myagent",
            "description": "x",
            "tools": None,
            "max_steps": 10,
            "stop_phrase": "TASK_COMPLETE",
            "system_prompt": "Do stuff.",
        },
    )
    assert not (tmp_path / ".hive" / "agents" / "myagent.json").exists()


def test_get_agent_configs_reads_md(tmp_path):
    create_workspace(tmp_path)
    save_agent_config(
        tmp_path,
        {
            "name": "a",
            "description": "desc",
            "tools": ["shell"],
            "max_steps": 5,
            "stop_phrase": "DONE",
            "system_prompt": "prompt",
        },
    )
    configs = get_agent_configs(tmp_path)
    assert len(configs) == 1
    assert configs[0]["name"] == "a"


def test_get_agent_configs_empty_when_no_dir(tmp_path):
    assert get_agent_configs(tmp_path) == []


def test_delete_agent_config_removes_md(tmp_path):
    create_workspace(tmp_path)
    save_agent_config(
        tmp_path,
        {
            "name": "del-me",
            "description": "x",
            "tools": None,
            "max_steps": 10,
            "stop_phrase": "TASK_COMPLETE",
            "system_prompt": "x",
        },
    )
    delete_agent_config(tmp_path, "del-me")
    assert not (tmp_path / ".hive" / "agents" / "del-me.md").exists()


def test_get_agent_configs_migrates_json(tmp_path):
    create_workspace(tmp_path)
    agents_dir = tmp_path / ".hive" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_data = {
        "name": "legacy",
        "description": "old",
        "tools": None,
        "max_steps": 10,
        "stop_phrase": "TASK_COMPLETE",
        "system_prompt": "old prompt",
    }
    (agents_dir / "legacy.json").write_text(json.dumps(agent_data), encoding="utf-8")
    configs = get_agent_configs(tmp_path)
    assert any(c["name"] == "legacy" for c in configs)
    assert not (agents_dir / "legacy.json").exists()
    assert (agents_dir / "legacy.md").exists()


# ---------------------------------------------------------------------------
# Global agent CRUD
# ---------------------------------------------------------------------------


@pytest.fixture()
def global_agents_dir(tmp_path, monkeypatch):
    """Redirect global agent storage to a temp directory."""
    import hive.workspace as ws_mod

    global_dir = tmp_path / "global-agents"
    monkeypatch.setattr(ws_mod, "get_global_agents_dir", lambda: global_dir)
    return global_dir


def test_save_global_agent_config_creates_md(global_agents_dir):
    from hive.workspace import save_global_agent_config

    save_global_agent_config(
        {
            "name": "g-agent",
            "description": "x",
            "tools": None,
            "max_steps": 10,
            "stop_phrase": "TASK_COMPLETE",
            "system_prompt": "hi",
        }
    )
    assert (global_agents_dir / "g-agent.md").exists()


def test_get_global_agent_configs_reads_md(global_agents_dir):
    from hive.workspace import get_global_agent_configs, save_global_agent_config

    save_global_agent_config(
        {
            "name": "g2",
            "description": "x",
            "tools": None,
            "max_steps": 10,
            "stop_phrase": "TASK_COMPLETE",
            "system_prompt": "hi",
        }
    )
    configs = get_global_agent_configs()
    assert any(c["name"] == "g2" for c in configs)


def test_delete_global_agent_config(global_agents_dir):
    from hive.workspace import delete_global_agent_config, save_global_agent_config

    save_global_agent_config(
        {
            "name": "del-global",
            "description": "x",
            "tools": None,
            "max_steps": 10,
            "stop_phrase": "TASK_COMPLETE",
            "system_prompt": "hi",
        }
    )
    delete_global_agent_config("del-global")
    assert not (global_agents_dir / "del-global.md").exists()
