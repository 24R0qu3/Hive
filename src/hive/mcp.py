"""MCP client — connects Hive to Model Context Protocol servers."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
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
    scope: str = "local"  # "local" or "global" — not persisted

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
    """Holds a live MCP session, its cached tool list, and the task keeping it alive."""

    def __init__(
        self,
        session,
        tools: list,
        config: MCPServerConfig,
        task: "asyncio.Task",
    ) -> None:
        self.session = session
        self.tools = tools  # list[mcp.types.Tool]
        self.config = config
        self.task = task  # asyncio.Task running _run_server — cancel to disconnect


class MCPManager:
    """Manages connections to one or more MCP servers.

    Runs a dedicated asyncio event loop on a background daemon thread so that
    async MCP calls can be made from synchronous Hive code via
    ``asyncio.run_coroutine_threadsafe``.

    Each connection is kept alive by a long-running ``_run_server`` task.
    Disconnecting cancels that task, which lets anyio's cancel scopes (used
    inside ``stdio_client``) unwind cleanly in the task that entered them.
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
        """Start a long-running connection task and wait until it is ready."""
        ready = threading.Event()
        error_box: list[Exception] = []
        asyncio.run_coroutine_threadsafe(
            self._run_server(config, ready, error_box), self._loop
        )
        if not ready.wait(timeout):
            raise TimeoutError(
                f"MCP server '{config.name}' did not connect within {timeout}s"
            )
        if error_box:
            raise error_box[0]

    def disconnect(self, name: str, timeout: int = 5) -> None:
        """Cancel the connection task; anyio cleans up its own cancel scopes."""
        with self._lock:
            conn = self._conns.get(name)
        if conn is None:
            return

        async def _cancel(task: asyncio.Task) -> None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        future = asyncio.run_coroutine_threadsafe(_cancel(conn.task), self._loop)
        try:
            future.result(timeout=timeout)
        except Exception:
            pass

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

    def compact_manifest(self) -> str | None:
        """Return a brief tool listing for all connected servers — no parameter schemas.

        Returns None when no servers are connected.  Each server appears on one
        line with its tool names so the model knows what is available without
        consuming context on full JSON schemas.
        """
        with self._lock:
            snapshot = dict(self._conns)
        if not snapshot:
            return None
        lines = ["MCP servers available (/use <name> activates full schemas):"]
        for server_name, conn in snapshot.items():
            names = [f"{server_name}__{tool.name}" for tool in conn.tools]
            preview = ", ".join(names[:10])
            if len(names) > 10:
                preview += f" (+{len(names) - 10} more)"
            lines.append(f"\u2022 {server_name}: {preview}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal async helpers
    # ------------------------------------------------------------------

    async def _run_server(
        self,
        config: MCPServerConfig,
        ready: threading.Event,
        error_box: list[Exception],
    ) -> None:
        """Long-running coroutine that holds one MCP connection open.

        Registers itself in ``self._conns`` once the session is ready, then
        awaits an event that is never set — keeping the ``stdio_client`` and
        ``ClientSession`` context managers alive until this task is cancelled.
        Cancellation causes both context managers to unwind inside this task,
        which satisfies anyio's requirement that cancel scopes are exited in
        the same task that entered them.
        """
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        merged_env = {**os.environ, **config.env}
        expanded_command = _expand_env(config.command, config.env)
        expanded_args = [_expand_env(a, config.env) for a in config.args]
        params = StdioServerParameters(
            command=expanded_command,
            args=expanded_args,
            env=merged_env,
        )
        devnull = open(os.devnull, "w")
        try:
            async with stdio_client(params, errlog=devnull) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    with self._lock:
                        self._conns[config.name] = _ServerConn(
                            session=session,
                            tools=result.tools,
                            config=config,
                            task=asyncio.current_task(),
                        )
                    ready.set()
                    # Hold the connection open until this task is cancelled.
                    _never = asyncio.Event()
                    await _never.wait()
        except asyncio.CancelledError:
            pass  # normal disconnect path
        except Exception as exc:
            error_box.append(exc)
            ready.set()
        finally:
            devnull.close()
            with self._lock:
                self._conns.pop(config.name, None)

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
                                config = conn.config
                                self.disconnect(name)
                                self.connect(config, timeout=15)
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
