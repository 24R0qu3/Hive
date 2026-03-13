"""MCP client — connects Hive to Model Context Protocol servers."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _expand_env(value: str, extra: dict[str, str]) -> str:
    """Expand $VAR, ${VAR} (Unix) and $env:VAR (PowerShell style) in value."""
    merged = {**os.environ, **extra}
    # PowerShell: $env:VAR
    value = re.sub(
        r"\$env:([A-Za-z_][A-Za-z0-9_]*)",
        lambda m: merged.get(m.group(1), m.group(0)),
        value,
    )
    # Unix: ${VAR}
    value = re.sub(
        r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
        lambda m: merged.get(m.group(1), m.group(0)),
        value,
    )
    # Unix: $VAR (not followed by word char)
    value = re.sub(
        r"\$([A-Za-z_][A-Za-z0-9_]*)(?!\w)",
        lambda m: merged.get(m.group(1), m.group(0)),
        value,
    )
    return value


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MCPServerConfig":
        return cls(
            name=d["name"],
            command=d["command"],
            args=d.get("args", []),
            env=d.get("env", {}),
            enabled=d.get("enabled", True),
        )


class _ServerConn:
    """Holds a live MCP session and its cached tool list."""

    def __init__(
        self,
        session,
        tools: list,
        exit_stack: AsyncExitStack,
        config: MCPServerConfig,
    ) -> None:
        self.session = session
        self.tools = tools  # list[mcp.types.Tool]
        self.exit_stack = exit_stack
        self.config = config


class MCPManager:
    """Manages connections to one or more MCP servers.

    Runs a dedicated asyncio event loop on a background daemon thread so that
    async MCP calls can be made from synchronous Hive code via
    ``asyncio.run_coroutine_threadsafe``.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="mcp-event-loop"
        )
        self._thread.start()
        self._conns: dict[str, _ServerConn] = {}
        self._retry_counts: dict[str, int] = {}
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()
        self._monitor_thread = threading.Thread(
            target=self._health_monitor, daemon=True, name="mcp-health-monitor"
        )
        self._monitor_thread.start()

    # ------------------------------------------------------------------
    # Public synchronous API
    # ------------------------------------------------------------------

    def connect(self, config: MCPServerConfig, timeout: int = 15) -> None:
        """Connect to an MCP server and cache its tools. Raises on failure."""
        future = asyncio.run_coroutine_threadsafe(
            self._connect_async(config), self._loop
        )
        future.result(timeout=timeout)

    def disconnect(self, name: str, timeout: int = 5) -> None:
        """Disconnect from a server and clean up its resources."""
        if name not in self._conns:
            return
        with self._lock:
            conn = self._conns.pop(name, None)
        if conn is None:
            return
        future = asyncio.run_coroutine_threadsafe(conn.exit_stack.aclose(), self._loop)
        future.result(timeout=timeout)

    def shutdown(self, timeout: int = 5) -> None:
        """Signal the health monitor to stop, then disconnect all servers."""
        self._shutdown_event.set()
        self._monitor_thread.join(timeout=timeout)
        for name in list(self._conns.keys()):
            try:
                self.disconnect(name)
            except Exception:
                pass

    def reconnect(self, name: str, timeout: int = 15) -> None:
        """Disconnect and reconnect the named server using its stored config."""
        with self._lock:
            if name not in self._conns:
                raise KeyError(f"No MCP server connected with name '{name}'")
            config = self._conns[name].config
        self.disconnect(name)
        self._retry_counts[name] = 0
        self.connect(config, timeout)

    def list_tools(self) -> list[dict]:
        """Return Ollama-compatible tool schemas for all connected servers.

        Tool names are prefixed as ``servername__toolname`` to avoid collisions
        between servers.
        """
        schemas = []
        for server_name, conn in self._conns.items():
            for tool in conn.tools:
                schemas.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"{server_name}__{tool.name}",
                            "description": tool.description or "",
                            "parameters": tool.inputSchema,
                        },
                    }
                )
        return schemas

    def call_tool(self, prefixed_name: str, args: dict, timeout: int = 30) -> str:
        """Call a tool by its prefixed name and return the result as a string."""
        if "__" not in prefixed_name:
            return f"Invalid MCP tool name: '{prefixed_name}'."
        server_name, tool_name = prefixed_name.split("__", 1)
        if server_name not in self._conns:
            return f"MCP server '{server_name}' is not connected."
        conn = self._conns[server_name]
        future = asyncio.run_coroutine_threadsafe(
            conn.session.call_tool(tool_name, args), self._loop
        )
        result = future.result(timeout=timeout)
        parts = [item.text for item in result.content if hasattr(item, "text")]
        return "\n".join(parts)

    def servers(self) -> dict[str, _ServerConn]:
        """Return a snapshot of currently connected servers."""
        return dict(self._conns)

    # ------------------------------------------------------------------
    # Internal async helpers
    # ------------------------------------------------------------------

    async def _connect_async(self, config: MCPServerConfig) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        stack = AsyncExitStack()
        merged_env = {**os.environ, **config.env}
        expanded_command = _expand_env(config.command, config.env)
        expanded_args = [_expand_env(a, config.env) for a in config.args]
        params = StdioServerParameters(
            command=expanded_command,
            args=expanded_args,
            env=merged_env,
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        result = await session.list_tools()
        with self._lock:
            self._conns[config.name] = _ServerConn(
                session=session, tools=result.tools, exit_stack=stack, config=config
            )

    def _probe(self, conn: _ServerConn) -> bool:
        """Return False if the server session is no longer responsive."""
        try:
            future = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(conn.session.list_tools(), timeout=1.0),
                self._loop,
            )
            future.result(timeout=2)
            return True
        except Exception:
            return False

    def _health_monitor(self) -> None:
        """Background daemon: detect dead servers and reconnect with exponential backoff."""
        while not self._shutdown_event.wait(timeout=5.0):
            with self._lock:
                snapshot = list(self._conns.items())
            for name, conn in snapshot:
                if self._shutdown_event.is_set():
                    break
                try:
                    alive = self._probe(conn)
                except Exception:
                    alive = False
                if not alive:
                    attempt = self._retry_counts.get(name, 0) + 1
                    self._retry_counts[name] = attempt
                    if attempt <= 3:
                        delay = min(2**attempt, 30)
                        logger.warning(
                            "MCP server '%s' appears dead (attempt %d/3), reconnecting in %ds",
                            name,
                            attempt,
                            delay,
                        )
                        self._shutdown_event.wait(timeout=delay)
                        if not self._shutdown_event.is_set():
                            try:
                                future = asyncio.run_coroutine_threadsafe(
                                    self._connect_async(conn.config), self._loop
                                )
                                future.result(timeout=15)
                            except Exception as exc:
                                logger.error(
                                    "MCP reconnect failed for '%s': %s", name, exc
                                )
                    else:
                        logger.error(
                            "MCP server '%s' failed to reconnect after 3 attempts, giving up.",
                            name,
                        )
                        self._retry_counts.pop(name, None)
