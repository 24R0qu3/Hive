"""Tests for hive.mcp and MCP-related workspace helpers."""

import json

import pytest

from hive.mcp import MCPManager, MCPServerConfig, _expand_env
from hive.workspace import create_workspace, get_mcp_configs, save_mcp_configs

# ---------------------------------------------------------------------------
# _expand_env
# ---------------------------------------------------------------------------


def test_expand_env_dollar_var(monkeypatch):
    monkeypatch.setenv("MY_VAR", "hello")
    assert _expand_env("$MY_VAR", {}) == "hello"


def test_expand_env_braced_var(monkeypatch):
    monkeypatch.setenv("MY_VAR", "world")
    assert _expand_env("${MY_VAR}", {}) == "world"


def test_expand_env_powershell_style(monkeypatch):
    monkeypatch.setenv("PS_VAR", "psvalue")
    assert _expand_env("$env:PS_VAR", {}) == "psvalue"


def test_expand_env_unknown_var_left_as_is(monkeypatch):
    # Ensure the variable does not exist
    monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
    result = _expand_env("$DEFINITELY_NOT_SET", {})
    assert result == "$DEFINITELY_NOT_SET"


def test_expand_env_no_variables():
    value = "plain string with no variables"
    assert _expand_env(value, {}) == value


def test_expand_env_extra_dict_overrides_env(monkeypatch):
    monkeypatch.setenv("OVERRIDE_VAR", "from_env")
    result = _expand_env("$OVERRIDE_VAR", {"OVERRIDE_VAR": "from_extra"})
    assert result == "from_extra"


def test_expand_env_extra_dict_provides_unknown():
    result = _expand_env("$EXTRA_ONLY", {"EXTRA_ONLY": "injected"})
    assert result == "injected"


def test_expand_env_mixed_styles(monkeypatch):
    monkeypatch.setenv("A", "alpha")
    monkeypatch.setenv("B", "beta")
    result = _expand_env("$A and ${B}", {})
    assert result == "alpha and beta"


# ---------------------------------------------------------------------------
# MCPServerConfig
# ---------------------------------------------------------------------------


def test_mcp_server_config_env_defaults_to_empty_dict():
    cfg = MCPServerConfig(name="srv", command="cmd")
    assert cfg.env == {}


def test_mcp_server_config_to_dict_includes_env():
    cfg = MCPServerConfig(name="srv", command="cmd", env={"KEY": "val"})
    d = cfg.to_dict()
    assert "env" in d
    assert d["env"] == {"KEY": "val"}


def test_mcp_server_config_from_dict_roundtrips_env():
    original = MCPServerConfig(
        name="myserver",
        command="npx",
        args=["--arg"],
        env={"TOKEN": "abc"},
        enabled=True,
    )
    restored = MCPServerConfig.from_dict(original.to_dict())
    assert restored.env == {"TOKEN": "abc"}
    assert restored.name == original.name
    assert restored.command == original.command
    assert restored.args == original.args
    assert restored.enabled == original.enabled


def test_mcp_server_config_from_dict_defaults_env_when_absent():
    d = {"name": "srv", "command": "node"}
    cfg = MCPServerConfig.from_dict(d)
    assert cfg.env == {}


def test_mcp_server_config_from_dict_defaults_enabled_when_absent():
    d = {"name": "srv", "command": "node"}
    cfg = MCPServerConfig.from_dict(d)
    assert cfg.enabled is True


def test_mcp_server_config_from_dict_defaults_args_when_absent():
    d = {"name": "srv", "command": "node"}
    cfg = MCPServerConfig.from_dict(d)
    assert cfg.args == []


# ---------------------------------------------------------------------------
# get_mcp_configs / save_mcp_configs
# ---------------------------------------------------------------------------


def test_get_mcp_configs_returns_empty_list_when_file_absent(tmp_path):
    create_workspace(tmp_path)
    assert get_mcp_configs(tmp_path) == []


def test_get_mcp_configs_returns_empty_list_when_no_workspace(tmp_path):
    # No .hive/ dir at all
    assert get_mcp_configs(tmp_path) == []


def test_save_and_get_mcp_configs_roundtrip(tmp_path):
    create_workspace(tmp_path)
    configs = [
        {"name": "alpha", "command": "node", "args": ["server.js"], "env": {}, "enabled": True},
        {"name": "beta", "command": "python", "args": ["-m", "srv"], "env": {"X": "1"}, "enabled": False},
    ]
    save_mcp_configs(tmp_path, configs)
    loaded = get_mcp_configs(tmp_path)
    assert loaded == configs


def test_save_mcp_configs_writes_valid_json(tmp_path):
    create_workspace(tmp_path)
    configs = [{"name": "srv", "command": "cmd", "args": [], "env": {}, "enabled": True}]
    save_mcp_configs(tmp_path, configs)
    raw = (tmp_path / ".hive" / "mcp.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed == configs


def test_save_mcp_configs_overwrites_previous(tmp_path):
    create_workspace(tmp_path)
    save_mcp_configs(tmp_path, [{"name": "old", "command": "x", "args": [], "env": {}, "enabled": True}])
    save_mcp_configs(tmp_path, [{"name": "new", "command": "y", "args": [], "env": {}, "enabled": True}])
    loaded = get_mcp_configs(tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["name"] == "new"


# ---------------------------------------------------------------------------
# MCPManager
# ---------------------------------------------------------------------------


def _make_manager():
    """Return an MCPManager whose background event loop is running."""
    return MCPManager()


def test_mcp_manager_monitor_thread_is_daemon():
    mgr = _make_manager()
    try:
        assert mgr._monitor_thread.daemon is True
    finally:
        mgr.shutdown(timeout=1)


def test_mcp_manager_monitor_thread_name():
    mgr = _make_manager()
    try:
        assert mgr._monitor_thread.name == "mcp-health-monitor"
    finally:
        mgr.shutdown(timeout=1)


def test_mcp_manager_is_alive_after_init():
    mgr = _make_manager()
    try:
        assert mgr._monitor_thread.is_alive() is True
    finally:
        mgr.shutdown(timeout=1)


def test_mcp_manager_shutdown_does_not_raise_when_no_servers():
    mgr = _make_manager()
    # Should complete without raising even when _conns is empty
    mgr.shutdown(timeout=2)


def test_mcp_manager_shutdown_stops_monitor_thread():
    mgr = _make_manager()
    mgr.shutdown(timeout=2)
    # After shutdown the monitor should have exited (join returned)
    # We verify the shutdown event is set as the reliable signal
    assert mgr._shutdown_event.is_set()


def test_mcp_manager_reconnect_raises_key_error_for_unknown_name():
    mgr = _make_manager()
    try:
        with pytest.raises(KeyError, match="no_such_server"):
            mgr.reconnect("no_such_server")
    finally:
        mgr.shutdown(timeout=1)


def test_mcp_manager_servers_returns_empty_dict_initially():
    mgr = _make_manager()
    try:
        assert mgr.servers() == {}
    finally:
        mgr.shutdown(timeout=1)


def test_mcp_manager_list_tools_returns_empty_list_when_no_servers():
    mgr = _make_manager()
    try:
        assert mgr.list_tools() == []
    finally:
        mgr.shutdown(timeout=1)


def test_mcp_manager_call_tool_invalid_name_returns_error_string():
    mgr = _make_manager()
    try:
        result = mgr.call_tool("no_double_underscore", {})
        assert "Invalid MCP tool name" in result
    finally:
        mgr.shutdown(timeout=1)


def test_mcp_manager_call_tool_disconnected_server_returns_error_string():
    mgr = _make_manager()
    try:
        result = mgr.call_tool("ghost__sometool", {})
        assert "not connected" in result
    finally:
        mgr.shutdown(timeout=1)


def test_mcp_manager_disconnect_unknown_name_does_not_raise():
    mgr = _make_manager()
    try:
        # disconnect on a non-existent name must be a no-op
        mgr.disconnect("nonexistent")
    finally:
        mgr.shutdown(timeout=1)
