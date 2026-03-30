"""Tests for hive.commands — registry, tool schemas, and executor."""

import json

from hive.commands import (
    AI_TOOLS,
    COMMAND_NAMES,
    COMMAND_REGISTRY,
    SUB_COMMANDS,
    SYSTEM_PROMPT,
    CommandDoc,
    _get_command_info,
    _list_commands,
    run_tool,
)

# ---------------------------------------------------------------------------
# CommandDoc dataclass
# ---------------------------------------------------------------------------


def test_command_doc_fields():
    cmd = CommandDoc(name="/test", usage="/test <arg>", description="Does a thing.")
    assert cmd.name == "/test"
    assert cmd.usage == "/test <arg>"
    assert cmd.description == "Does a thing."
    assert cmd.notes is None


def test_command_doc_with_notes():
    cmd = CommandDoc(
        name="/test", usage="/test", description="x", notes="Some extra info."
    )
    assert cmd.notes == "Some extra info."


# ---------------------------------------------------------------------------
# COMMAND_REGISTRY
# ---------------------------------------------------------------------------


def test_registry_is_non_empty():
    assert len(COMMAND_REGISTRY) > 0


def test_registry_entries_are_command_docs():
    for cmd in COMMAND_REGISTRY:
        assert isinstance(cmd, CommandDoc)


def test_registry_names_start_with_slash():
    for cmd in COMMAND_REGISTRY:
        assert cmd.name.startswith("/"), f"{cmd.name} should start with /"


def test_registry_usages_start_with_slash():
    for cmd in COMMAND_REGISTRY:
        assert cmd.usage.startswith("/"), f"{cmd.usage} should start with /"


def test_registry_contains_exit():
    names = [cmd.name for cmd in COMMAND_REGISTRY]
    assert "/exit" in names


def test_registry_contains_model():
    names = [cmd.name for cmd in COMMAND_REGISTRY]
    assert "/model" in names


def test_registry_contains_sessions():
    names = [cmd.name for cmd in COMMAND_REGISTRY]
    assert "/sessions" in names


# ---------------------------------------------------------------------------
# COMMAND_NAMES
# ---------------------------------------------------------------------------


def test_command_names_length_matches_registry():
    assert len(COMMAND_NAMES) == len(COMMAND_REGISTRY)


def test_command_names_are_bare_slash_names():
    for name in COMMAND_NAMES:
        assert name.startswith("/")
        assert " " not in name


def test_command_names_match_registry():
    expected = [cmd.name for cmd in COMMAND_REGISTRY]
    assert COMMAND_NAMES == expected


# ---------------------------------------------------------------------------
# SUB_COMMANDS
# ---------------------------------------------------------------------------


def test_sub_commands_keys_exist_in_command_names():
    for key in SUB_COMMANDS:
        assert key in COMMAND_NAMES, f"{key} in SUB_COMMANDS is not in COMMAND_NAMES"


def test_sub_commands_values_are_non_empty_lists():
    for key, subs in SUB_COMMANDS.items():
        assert isinstance(subs, list) and len(subs) > 0, f"{key} has empty sub-commands"


def test_sub_commands_agent_has_expected_subs():
    assert set(SUB_COMMANDS["/agent"]) >= {"add", "list", "delete", "edit"}


def test_sub_commands_mcp_has_manage():
    assert "manage" in SUB_COMMANDS["/mcp"]


# ---------------------------------------------------------------------------
# _list_commands
# ---------------------------------------------------------------------------


def test_list_commands_returns_string():
    result = _list_commands()
    assert isinstance(result, str)


def test_list_commands_includes_all_commands():
    result = _list_commands()
    for cmd in COMMAND_REGISTRY:
        assert cmd.name in result


def test_list_commands_includes_descriptions():
    result = _list_commands()
    for cmd in COMMAND_REGISTRY:
        assert cmd.description in result


def test_list_commands_one_line_per_command():
    result = _list_commands()
    lines = result.strip().splitlines()
    assert len(lines) == len(COMMAND_REGISTRY)


# ---------------------------------------------------------------------------
# _get_command_info
# ---------------------------------------------------------------------------


def test_get_command_info_known_command():
    result = _get_command_info("/exit")
    assert "exit" in result.lower()
    assert "Usage:" in result
    assert "Description:" in result


def test_get_command_info_adds_slash():
    """Passing 'exit' without slash should still work."""
    with_slash = _get_command_info("/exit")
    without_slash = _get_command_info("exit")
    assert with_slash == without_slash


def test_get_command_info_model_includes_notes():
    result = _get_command_info("/model")
    assert "Notes:" in result


def test_get_command_info_exit_no_notes():
    result = _get_command_info("/exit")
    assert "Notes:" not in result


def test_get_command_info_unknown_command():
    result = _get_command_info("/doesnotexist")
    assert "Unknown" in result
    assert "/doesnotexist" in result


# ---------------------------------------------------------------------------
# run_tool
# ---------------------------------------------------------------------------


def test_run_tool_list_commands():
    result = run_tool("list_commands", {})
    assert isinstance(result, str)
    for cmd in COMMAND_REGISTRY:
        assert cmd.name in result


def test_run_tool_get_command_info():
    result = run_tool("get_command_info", {"name": "/exit"})
    assert "exit" in result.lower()
    assert "Usage:" in result


def test_run_tool_get_command_info_no_slash():
    result = run_tool("get_command_info", {"name": "exit"})
    assert "exit" in result.lower()


def test_run_tool_unknown_tool():
    result = run_tool("nonexistent_tool", {})
    assert "Unknown" in result


def test_run_tool_get_command_info_missing_arg():
    """Empty name should return unknown-command message, not raise."""
    result = run_tool("get_command_info", {})
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# AI_TOOLS schemas
# ---------------------------------------------------------------------------


def test_ai_tools_is_list():
    assert isinstance(AI_TOOLS, list)


def test_ai_tools_has_three_tools():
    assert len(AI_TOOLS) == 3


def test_ai_tools_have_required_keys():
    for tool in AI_TOOLS:
        assert tool["type"] == "function"
        assert "function" in tool
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn


def test_ai_tools_list_commands_schema():
    names = [t["function"]["name"] for t in AI_TOOLS]
    assert "list_commands" in names


def test_ai_tools_get_command_info_schema():
    names = [t["function"]["name"] for t in AI_TOOLS]
    assert "get_command_info" in names


def test_ai_tools_get_command_info_has_name_param():
    tool = next(t for t in AI_TOOLS if t["function"]["name"] == "get_command_info")
    props = tool["function"]["parameters"]["properties"]
    assert "name" in props
    assert props["name"]["type"] == "string"


def test_ai_tools_schemas_are_json_serialisable():
    json.dumps(AI_TOOLS)  # must not raise


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT
# ---------------------------------------------------------------------------


def test_system_prompt_is_string():
    assert isinstance(SYSTEM_PROMPT, str) and SYSTEM_PROMPT


def test_system_prompt_mentions_commands():
    for cmd in COMMAND_REGISTRY:
        assert cmd.name in SYSTEM_PROMPT


def test_system_prompt_mentions_slash_commands():
    assert "/" in SYSTEM_PROMPT
