"""MCP client — connects Hive to Model Context Protocol servers."""

from __future__ import annotations

import asyncio
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MCPServerConfig":
        return cls(
            name=d["name"],
            command=d["command"],
            args=d.get("args", []),
            enabled=d.get("enabled", True),
        )


class _ServerConn:
    """Holds a live MCP session and its cached tool list."""

    def __init__(self, session, tools: list, exit_stack: AsyncExitStack) -> None:
        self.session = session
        self.tools = tools  # list[mcp.types.Tool]
        self.exit_stack = exit_stack


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
        conn = self._conns.pop(name)
        future = asyncio.run_coroutine_threadsafe(
            conn.exit_stack.aclose(), self._loop
        )
        future.result(timeout=timeout)

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
        params = StdioServerParameters(command=config.command, args=config.args)
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        result = await session.list_tools()
        self._conns[config.name] = _ServerConn(
            session=session, tools=result.tools, exit_stack=stack
        )
