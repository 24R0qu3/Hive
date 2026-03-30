"""Tests for hive.agent — AgentDefinition and load_agent_definitions scoping."""

import pytest

import hive.workspace as ws_mod
from hive.agent import AgentDefinition, load_agent_definitions
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
