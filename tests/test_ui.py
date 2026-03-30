"""Tests for hive.ui.app — _load_history (via history module) and handle_input."""

import logging
from unittest.mock import MagicMock

import pytest

from hive.ui.history import load_history_file
from hive.workspace import create_workspace, set_language

# ---------------------------------------------------------------------------
# load_history_file (previously _load_history in app.py)
# ---------------------------------------------------------------------------


def test_returns_empty_when_file_missing(tmp_path):
    assert load_history_file(tmp_path / "history") == []


def test_returns_empty_when_file_is_empty(tmp_path):

    p = tmp_path / "history"
    p.write_text("", encoding="utf-8")
    assert load_history_file(p) == []


def test_loads_json_lines(tmp_path):
    import json

    p = tmp_path / "history"
    p.write_text(
        "\n".join(json.dumps(e) for e in ["hello", "world"]),
        encoding="utf-8",
    )
    assert load_history_file(p) == ["hello", "world"]


def test_loads_multiline_entry(tmp_path):
    import json

    p = tmp_path / "history"
    p.write_text(json.dumps("line1\nline2"), encoding="utf-8")
    assert load_history_file(p) == ["line1\nline2"]


def test_migrates_old_filehistory_format(tmp_path):
    p = tmp_path / "history"
    p.write_text(
        "# 2026-02-27 23:32:21.239492\n+hello\n# 2026-02-27 23:32:21.239492\n+world\n",
        encoding="utf-8",
    )
    assert load_history_file(p) == ["hello", "world"]


def test_skips_timestamp_lines(tmp_path):
    p = tmp_path / "history"
    p.write_text("# 2026-02-27 23:32:21.239492\n", encoding="utf-8")
    assert load_history_file(p) == []


def test_skips_blank_lines(tmp_path):
    import json

    p = tmp_path / "history"
    p.write_text(
        json.dumps("hello") + "\n\n" + json.dumps("world") + "\n",
        encoding="utf-8",
    )
    assert load_history_file(p) == ["hello", "world"]


def test_mixed_old_and_new_format(tmp_path):
    import json

    p = tmp_path / "history"
    p.write_text(
        "# 2026-02-27 23:32:21.239492\n+old entry\n" + json.dumps("new entry") + "\n",
        encoding="utf-8",
    )
    assert load_history_file(p) == ["old entry", "new entry"]


# ---------------------------------------------------------------------------
# handle_input — shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_logger():
    root = logging.getLogger()
    original = list(root.handlers)
    root.handlers.clear()
    yield
    for h in root.handlers:
        h.close()
    root.handlers.clear()
    root.handlers.extend(original)


@pytest.fixture()
def hive_app(tmp_path, monkeypatch, _clean_logger):
    """A HiveApp wired to tmp_path with mocked user state and TUI app."""
    from prompt_toolkit.output import DummyOutput

    from hive.ui.app import HiveApp

    monkeypatch.setattr("hive.ui.app.get_user_name", lambda: "Test")
    monkeypatch.setattr("hive.ui.app.has_user_name", lambda: True)
    create_workspace(tmp_path)
    set_language(tmp_path, "en")
    app = HiveApp(tmp_path, trusted=True, _output=DummyOutput())
    app.app = MagicMock()
    return app


# ---------------------------------------------------------------------------
# handle_input — /exit
# ---------------------------------------------------------------------------


def test_handle_exit_calls_app_exit(hive_app):
    hive_app.handle_input("/exit")
    hive_app.app.exit.assert_called_once()


# ---------------------------------------------------------------------------
# handle_input — /name
# ---------------------------------------------------------------------------


def test_handle_name_activates_name_dialog(hive_app):
    hive_app.handle_input("/name")
    assert hive_app._awaiting_name is True
    assert hive_app._name_is_rename is True


def test_handle_name_invalidates_app(hive_app):
    hive_app.handle_input("/name")
    hive_app.app.invalidate.assert_called()


# ---------------------------------------------------------------------------
# handle_input — /language
# ---------------------------------------------------------------------------


def test_handle_language_activates_picker(hive_app):
    hive_app.handle_input("/language")
    assert hive_app._picking_language is True


def test_handle_language_invalidates_app(hive_app):
    hive_app.handle_input("/language")
    hive_app.app.invalidate.assert_called()


# ---------------------------------------------------------------------------
# handle_input — /resume
# ---------------------------------------------------------------------------


def test_handle_resume_activates_picker_when_sessions_exist(hive_app):
    # trusted=True already created one session in tmp_path
    hive_app.handle_input("/resume")
    assert hive_app._resuming is True
    assert len(hive_app._resume_sessions) >= 1


def test_handle_resume_prints_message_when_no_sessions(
    tmp_path, monkeypatch, _clean_logger
):
    """With a fresh workspace that has no prior sessions, /resume shows a message."""
    from prompt_toolkit.output import DummyOutput

    from hive.ui.app import HiveApp

    monkeypatch.setattr("hive.ui.app.get_user_name", lambda: "Test")
    monkeypatch.setattr("hive.ui.app.has_user_name", lambda: True)
    # Patch list_sessions to always return empty
    monkeypatch.setattr("hive.ui.app.list_sessions", lambda cwd: [])

    create_workspace(tmp_path)
    set_language(tmp_path, "en")
    app = HiveApp(tmp_path, trusted=True, _output=DummyOutput())
    app.app = MagicMock()

    app.handle_input("/resume")
    assert app._resuming is False
    assert any(app._output_lines)


# ---------------------------------------------------------------------------
# handle_input — /sessions
# ---------------------------------------------------------------------------


def test_handle_sessions_outputs_content(hive_app):
    # There's at least the session created by trusted=True
    hive_app.handle_input("/sessions")
    assert any(hive_app._output_lines)


def test_handle_sessions_contains_session_id(hive_app):
    hive_app.handle_input("/sessions")
    output = "\n".join(hive_app._output_lines)
    assert hive_app._session.id in output


# ---------------------------------------------------------------------------
# handle_input — /model
# ---------------------------------------------------------------------------


def test_handle_model_no_arg_opens_picker(hive_app, monkeypatch):
    monkeypatch.setattr(
        hive_app._provider, "list_models", lambda: ["llama3.2", "mistral"]
    )
    hive_app.handle_input("/model")
    assert hive_app._picking_model is True
    assert hive_app._model_list == ["llama3.2", "mistral"]


def test_handle_model_no_arg_no_ollama_prints_message(hive_app, monkeypatch):
    monkeypatch.setattr(hive_app._provider, "list_models", lambda: [])
    hive_app.handle_input("/model")
    assert hive_app._picking_model is False
    output = "\n".join(hive_app._output_lines)
    assert "Ollama" in output or "model" in output.lower()


def test_handle_model_set_updates_model_attribute(hive_app):
    hive_app.handle_input("/model mistral")
    assert hive_app._model == "mistral"


def test_handle_model_set_prints_confirmation(hive_app):
    hive_app.handle_input("/model mistral")
    output = "\n".join(hive_app._output_lines)
    assert "mistral" in output


def test_handle_model_trailing_space_opens_picker(hive_app, monkeypatch):
    # "/model " with trailing whitespace is treated same as "/model" by split(None,1)
    monkeypatch.setattr(hive_app._provider, "list_models", lambda: ["llama3.2"])
    hive_app.handle_input("/model ")
    assert hive_app._picking_model is True


# ---------------------------------------------------------------------------
# handle_input — /use
# ---------------------------------------------------------------------------


def test_handle_use_no_arg_prints_none_active_message(hive_app):
    hive_app.handle_input("/use")
    output = "\n".join(hive_app._output_lines)
    assert "No MCP" in output or "active" in output.lower()


def test_handle_use_unknown_server_prints_error(hive_app):
    hive_app.handle_input("/use ghost_server")
    output = "\n".join(hive_app._output_lines)
    assert "ghost_server" in output
    assert "ghost_server" not in hive_app._active_mcp_servers


def test_handle_use_activates_connected_server(hive_app, monkeypatch):
    monkeypatch.setattr(hive_app._mcp, "servers", lambda: {"myserver": object()})
    hive_app.handle_input("/use myserver")
    assert "myserver" in hive_app._active_mcp_servers


def test_handle_use_toggles_off_active_server(hive_app, monkeypatch):
    monkeypatch.setattr(hive_app._mcp, "servers", lambda: {"myserver": object()})
    hive_app._active_mcp_servers.add("myserver")
    hive_app.handle_input("/use myserver")
    assert "myserver" not in hive_app._active_mcp_servers


def test_handle_use_all_activates_all_connected(hive_app, monkeypatch):
    monkeypatch.setattr(
        hive_app._mcp, "servers", lambda: {"alpha": object(), "beta": object()}
    )
    hive_app.handle_input("/use all")
    assert "alpha" in hive_app._active_mcp_servers
    assert "beta" in hive_app._active_mcp_servers


def test_handle_use_none_clears_active_servers(hive_app, monkeypatch):
    monkeypatch.setattr(hive_app._mcp, "servers", lambda: {"alpha": object()})
    hive_app._active_mcp_servers = {"alpha", "beta"}
    hive_app.handle_input("/use none")
    assert hive_app._active_mcp_servers == set()


def test_handle_use_shows_available_when_connected(hive_app, monkeypatch):
    monkeypatch.setattr(hive_app._mcp, "servers", lambda: {"myserver": object()})
    hive_app.handle_input("/use")
    output = "\n".join(hive_app._output_lines)
    assert "myserver" in output


def test_handle_use_server_plus_query_activates_and_routes_to_ai(hive_app, monkeypatch):
    monkeypatch.setattr(hive_app._mcp, "servers", lambda: {"engra": object()})
    routed = []
    monkeypatch.setattr(hive_app, "_start_ai_response", lambda q: routed.append(q))
    hive_app.handle_input("/use engra search for file server property message")
    assert "engra" in hive_app._active_mcp_servers
    assert routed == ["search for file server property message"]


def test_handle_use_server_plus_query_skips_activation_message_if_already_active(
    hive_app, monkeypatch
):
    monkeypatch.setattr(hive_app._mcp, "servers", lambda: {"engra": object()})
    hive_app._active_mcp_servers.add("engra")
    routed = []
    monkeypatch.setattr(hive_app, "_start_ai_response", lambda q: routed.append(q))
    before_lines = len(hive_app._output_lines)
    hive_app.handle_input("/use engra find something")
    assert len(hive_app._output_lines) == before_lines  # no extra activation message
    assert routed == ["find something"]


# ---------------------------------------------------------------------------
# handle_input — non-command routes to AI
# ---------------------------------------------------------------------------


def test_handle_non_command_calls_start_ai_response(hive_app, monkeypatch):
    called = []
    monkeypatch.setattr(
        hive_app, "_start_ai_response", lambda text: called.append(text)
    )
    hive_app.handle_input("hello world")
    assert called == ["hello world"]


def test_handle_non_command_multiple_words(hive_app, monkeypatch):
    called = []
    monkeypatch.setattr(
        hive_app, "_start_ai_response", lambda text: called.append(text)
    )
    hive_app.handle_input("tell me a joke")
    assert called == ["tell me a joke"]


# ---------------------------------------------------------------------------
# print
# ---------------------------------------------------------------------------


def test_print_appends_to_output_lines(hive_app):
    before = len(hive_app._output_lines)
    hive_app.print("hello")
    assert len(hive_app._output_lines) > before


def test_print_resets_scroll_offset(hive_app):
    hive_app._scroll_offset = 10
    hive_app.print("test")
    assert hive_app._scroll_offset == 0


def test_print_renders_rich_table(hive_app):
    from rich.table import Table

    t = Table()
    t.add_column("Name")
    t.add_row("Alice")
    hive_app.print(t)
    output = "\n".join(hive_app._output_lines)
    assert "Alice" in output


# ---------------------------------------------------------------------------
# Sub-command suggestion (_update_suggestion via buffer.on_text_changed)
# ---------------------------------------------------------------------------


def test_suggestion_top_level_command(hive_app):
    hive_app.input_field.text = "/age"
    suggestion = hive_app.input_field.buffer.suggestion
    assert suggestion is not None
    assert suggestion.text == "nt"  # "/age" → "/agent"


def test_suggestion_sub_command(hive_app):
    hive_app.input_field.text = "/agent ad"
    suggestion = hive_app.input_field.buffer.suggestion
    assert suggestion is not None
    assert suggestion.text == "d"  # "/agent ad" → "/agent add"


def test_suggestion_sub_command_empty_prefix(hive_app):
    # "/agent " with trailing space — first sub-command should be suggested
    hive_app.input_field.text = "/agent a"
    suggestion = hive_app.input_field.buffer.suggestion
    assert suggestion is not None  # "add" starts with "a"


def test_suggestion_clears_on_non_slash(hive_app):
    hive_app.input_field.text = "hello"
    assert hive_app.input_field.buffer.suggestion is None


def test_suggestion_none_on_complete_command_without_subs(hive_app):
    # "/exit" is complete — no sub-commands, no further suggestion
    hive_app.input_field.text = "/exit"
    suggestion = hive_app.input_field.buffer.suggestion
    # No extension possible
    assert suggestion is None


# ---------------------------------------------------------------------------
# _SlashLexer — sub-command highlighting
# ---------------------------------------------------------------------------


def test_slash_lexer_highlights_command():
    from prompt_toolkit.document import Document

    from hive.ui.app import _SlashLexer

    lexer = _SlashLexer()
    doc = Document("/agent add")
    get_line = lexer.lex_document(doc)
    fragments = get_line(0)
    styles = [f[0] for f in fragments if f[1].strip()]
    assert "class:slash-cmd" in styles


def test_slash_lexer_highlights_subcommand():
    from prompt_toolkit.document import Document

    from hive.ui.app import _SlashLexer

    lexer = _SlashLexer()
    doc = Document("/agent add")
    get_line = lexer.lex_document(doc)
    fragments = get_line(0)
    # find fragment with "add"
    sub_fragments = [f for f in fragments if f[1] == "add"]
    assert sub_fragments, "no fragment for 'add'"
    assert sub_fragments[0][0] == "class:slash-sub"


def test_slash_lexer_no_subcommand_highlight_for_unknown():
    from prompt_toolkit.document import Document

    from hive.ui.app import _SlashLexer

    lexer = _SlashLexer()
    doc = Document("/agent unknownsub")
    get_line = lexer.lex_document(doc)
    fragments = get_line(0)
    sub_fragments = [f for f in fragments if f[1] == "unknownsub"]
    assert sub_fragments
    assert sub_fragments[0][0] == ""  # not highlighted
