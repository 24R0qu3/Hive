"""Tests for hive.agent — AgentDefinition, AgentRunner, and load_agent_definitions scoping."""

import threading

import pytest

import hive.workspace as ws_mod
from hive.agent import (
    AgentDefinition,
    AgentRunner,
    _extract_text_tool_calls,
    load_agent_definitions,
)
from hive.workspace import create_workspace, save_agent_config, save_global_agent_config


@pytest.fixture()
def global_agents_dir(tmp_path, monkeypatch):
    """Redirect global agent storage to a temp directory."""
    global_dir = tmp_path / "global-agents"
    monkeypatch.setattr(ws_mod, "get_global_agents_dir", lambda: global_dir)
    return global_dir


# ---------------------------------------------------------------------------
# AgentDefinition
# ---------------------------------------------------------------------------


def test_agent_definition_defaults():
    defn = AgentDefinition(name="x", description="d", system_prompt="p")
    assert defn.tools is None
    assert defn.max_steps == 10
    assert defn.stop_phrase == "TASK_COMPLETE"
    assert defn.scope == "local"


def test_agent_definition_scope_field():
    defn = AgentDefinition(name="x", description="d", system_prompt="p", scope="global")
    assert defn.scope == "global"


def test_agent_definition_scope_not_in_to_dict():
    defn = AgentDefinition(name="x", description="d", system_prompt="p", scope="global")
    assert "scope" not in defn.to_dict()


def test_agent_definition_from_dict_scope_default():
    defn = AgentDefinition.from_dict(
        {"name": "x", "description": "d", "system_prompt": "p"}
    )
    assert defn.scope == "local"


def test_agent_definition_from_dict_scope_explicit():
    defn = AgentDefinition.from_dict(
        {"name": "x", "description": "d", "system_prompt": "p"}, scope="global"
    )
    assert defn.scope == "global"


# ---------------------------------------------------------------------------
# load_agent_definitions — scope priority
# ---------------------------------------------------------------------------


def _agent_config(name: str, description: str = "desc") -> dict:
    return {
        "name": name,
        "description": description,
        "tools": None,
        "max_steps": 10,
        "stop_phrase": "TASK_COMPLETE",
        "system_prompt": f"I am {name}.",
    }


def test_load_includes_builtins(tmp_path, global_agents_dir):
    create_workspace(tmp_path)
    definitions = load_agent_definitions(tmp_path)
    assert "shell-task" in definitions


def test_builtin_scope_is_builtin(tmp_path, global_agents_dir):
    create_workspace(tmp_path)
    definitions = load_agent_definitions(tmp_path)
    assert definitions["shell-task"].scope == "builtin"


def test_local_agent_scope_is_local(tmp_path, global_agents_dir):
    create_workspace(tmp_path)
    save_agent_config(tmp_path, _agent_config("local-only"))
    definitions = load_agent_definitions(tmp_path)
    assert definitions["local-only"].scope == "local"


def test_global_agent_scope_is_global(tmp_path, global_agents_dir):
    create_workspace(tmp_path)
    save_global_agent_config(_agent_config("global-only"))
    definitions = load_agent_definitions(tmp_path)
    assert definitions["global-only"].scope == "global"


def test_local_overrides_global(tmp_path, global_agents_dir):
    create_workspace(tmp_path)
    save_global_agent_config(_agent_config("shared", description="global version"))
    save_agent_config(tmp_path, _agent_config("shared", description="local version"))
    definitions = load_agent_definitions(tmp_path)
    assert definitions["shared"].scope == "local"
    assert definitions["shared"].description == "local version"


def test_global_overrides_builtin(tmp_path, global_agents_dir):
    create_workspace(tmp_path)
    save_global_agent_config(_agent_config("shell-task", description="my custom shell"))
    definitions = load_agent_definitions(tmp_path)
    assert definitions["shell-task"].scope == "global"
    assert definitions["shell-task"].description == "my custom shell"


# ---------------------------------------------------------------------------
# _extract_text_tool_calls
# ---------------------------------------------------------------------------


def test_extract_text_tool_calls_parses_valid_json():
    text = '{"name": "shell", "arguments": {"command": "ls"}}'
    calls = _extract_text_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "shell"
    assert calls[0]["function"]["arguments"] == {"command": "ls"}


def test_extract_text_tool_calls_multiple_calls():
    text = (
        '{"name": "shell", "arguments": {"command": "ls"}} '
        "some text "
        '{"name": "shell", "arguments": {"command": "pwd"}}'
    )
    calls = _extract_text_tool_calls(text)
    assert len(calls) == 2
    assert calls[0]["function"]["arguments"]["command"] == "ls"
    assert calls[1]["function"]["arguments"]["command"] == "pwd"


def test_extract_text_tool_calls_no_match_returns_empty():
    assert _extract_text_tool_calls("no JSON here") == []
    assert _extract_text_tool_calls("") == []


def test_extract_text_tool_calls_ignores_invalid_json():
    # Looks like a match but is malformed JSON
    text = '{"name": "shell", "arguments": {bad}}'
    assert _extract_text_tool_calls(text) == []


def test_extract_text_tool_calls_ignores_object_missing_arguments():
    text = '{"name": "shell", "other": "field"}'
    assert _extract_text_tool_calls(text) == []


# ---------------------------------------------------------------------------
# AgentRunner helpers
# ---------------------------------------------------------------------------


def _make_definition(**kwargs) -> AgentDefinition:
    defaults = dict(name="test", description="d", system_prompt="You are helpful.")
    defaults.update(kwargs)
    return AgentDefinition(**defaults)


def _make_provider(responses: list):
    """Stub provider whose chat_step pops from *responses*.

    Each entry is either ``(text, tool_calls)`` or an exception to raise.
    """

    class _StubProvider:
        def chat_step(self, messages, model, tools=None, abort=None):
            item = responses.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

    return _StubProvider()


# ---------------------------------------------------------------------------
# AgentRunner — basic flow
# ---------------------------------------------------------------------------


def test_agent_runner_returns_success_on_stop_phrase():
    provider = _make_provider([("TASK_COMPLETE: all done", [])])
    runner = AgentRunner(provider, "model")
    defn = _make_definition()
    steps = []
    result = runner.run(
        defn, "do thing", lambda n, a: "", steps.append, [], threading.Event()
    )
    assert result.success is True
    assert "all done" in result.summary


def test_agent_runner_returns_success_when_no_tool_calls():
    provider = _make_provider([("Nothing to do.", [])])
    runner = AgentRunner(provider, "model")
    result = runner.run(
        _make_definition(),
        "do thing",
        lambda n, a: "",
        lambda s: None,
        [],
        threading.Event(),
    )
    assert result.success is True


def test_agent_runner_executes_tool_and_continues():
    responses = [
        ("", [{"function": {"name": "shell", "arguments": {"command": "ls"}}}]),
        ("TASK_COMPLETE", []),
    ]
    provider = _make_provider(responses)
    runner = AgentRunner(provider, "model")
    executed: list[tuple] = []
    result = runner.run(
        _make_definition(),
        "list files",
        lambda n, a: executed.append((n, a)) or "file.txt",
        lambda s: None,
        [],
        threading.Event(),
    )
    assert result.success is True
    assert executed == [("shell", {"command": "ls"})]


def test_agent_runner_hits_max_steps():
    # Always returns a tool call — never completes
    responses = [
        ("", [{"function": {"name": "shell", "arguments": {"command": "ls"}}}])
        for _ in range(5)
    ]
    provider = _make_provider(responses)
    defn = _make_definition(max_steps=5)
    result = runner = AgentRunner(provider, "model")
    result = runner.run(
        defn, "go", lambda n, a: "ok", lambda s: None, [], threading.Event()
    )
    assert result.success is False
    assert result.steps_taken == 5


def test_agent_runner_returns_error_on_provider_exception():
    provider = _make_provider([RuntimeError("boom")])
    runner = AgentRunner(provider, "model")
    result = runner.run(
        _make_definition(),
        "go",
        lambda n, a: "ok",
        lambda s: None,
        [],
        threading.Event(),
    )
    assert result.success is False
    assert "boom" in result.summary


def test_agent_runner_returns_friendly_error_on_tools_not_supported():
    from hive.ai import _ToolsNotSupported

    provider = _make_provider([_ToolsNotSupported()])
    runner = AgentRunner(provider, "phi4-mini:3.8b")
    result = runner.run(
        _make_definition(),
        "go",
        lambda n, a: "ok",
        lambda s: None,
        [{"type": "function", "function": {"name": "shell"}}],
        threading.Event(),
    )
    assert result.success is False
    assert "does not support tool calling" in result.summary
    assert "phi4-mini:3.8b" in result.summary


# ---------------------------------------------------------------------------
# AgentRunner — abort
# ---------------------------------------------------------------------------


def test_agent_runner_aborts_before_first_step():
    abort = threading.Event()
    abort.set()
    provider = _make_provider([])  # should never be called
    runner = AgentRunner(provider, "model")
    result = runner.run(
        _make_definition(), "go", lambda n, a: "ok", lambda s: None, [], abort
    )
    assert result.success is False
    assert "Aborted" in result.summary


def test_agent_runner_aborts_between_tool_calls():
    abort = threading.Event()

    def executor(name, args):
        abort.set()
        return "result"

    responses = [
        ("", [{"function": {"name": "shell", "arguments": {}}}]),
        ("TASK_COMPLETE", []),
    ]
    provider = _make_provider(responses)
    runner = AgentRunner(provider, "model")
    result = runner.run(
        _make_definition(max_steps=10),
        "go",
        executor,
        lambda s: None,
        [],
        abort,
    )
    assert result.success is False
    assert "Aborted" in result.summary


# ---------------------------------------------------------------------------
# AgentRunner — text_mode (model emits tool calls as raw JSON text)
# ---------------------------------------------------------------------------


def test_agent_runner_text_mode_parses_tool_calls_from_text():
    tool_call_text = '{"name": "shell", "arguments": {"command": "pwd"}}'
    responses = [
        (tool_call_text, []),  # model emits JSON text instead of structured call
        ("TASK_COMPLETE", []),
    ]
    provider = _make_provider(responses)
    runner = AgentRunner(provider, "model")
    executed: list[tuple] = []
    result = runner.run(
        _make_definition(),
        "go",
        lambda n, a: executed.append((n, a)) or "/home",
        lambda s: None,
        [],
        threading.Event(),
    )
    assert result.success is True
    assert executed == [("shell", {"command": "pwd"})]


def test_agent_runner_text_mode_uses_user_messages_for_history():
    """In text_mode the tool results go back as user messages, not tool messages."""
    tool_call_text = '{"name": "shell", "arguments": {"command": "ls"}}'
    sent_messages: list[list] = []

    class _CapturingProvider:
        def __init__(self):
            self._calls = 0

        def chat_step(self, messages, model, tools=None, abort=None):
            sent_messages.append(list(messages))
            self._calls += 1
            if self._calls == 1:
                return tool_call_text, []
            return "TASK_COMPLETE", []

    runner = AgentRunner(_CapturingProvider(), "model")
    runner.run(
        _make_definition(),
        "go",
        lambda n, a: "file.txt",
        lambda s: None,
        [],
        threading.Event(),
    )
    # Second call's messages should contain a user message with the tool result,
    # not a role=tool message.
    second_call_roles = [m["role"] for m in sent_messages[1]]
    assert "tool" not in second_call_roles
    assert "user" in second_call_roles
