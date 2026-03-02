"""AI provider interface and built-in Ollama implementation."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Protocol, runtime_checkable

DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_BASE_URL = "http://localhost:11434"

THINKING_MSGS = [
    "Consulting the digital oracle",
    "Summoning neural pathways",
    "Asking the electrons nicely",
    "Brewing intelligence",
    "Pondering the infinite",
    "Consulting the rubber duck",
    "Sacrificing RAM to the gods",
    "Convincing the weights to cooperate",
    "Untangling the tensors",
    "Whispering to the GPU",
    "Performing digital alchemy",
    "Shuffling the probability distributions",
    "Herding cats\u2026 I mean tokens",
    "Defragmenting the imagination",
    "Calibrating the nonsense filter",
    "Asking ChatGPT for advice (just kidding)",
    "Counting backwards from infinity",
    "Negotiating with the attention heads",
]


@runtime_checkable
class AIProvider(Protocol):
    """Minimal interface every AI backend must satisfy."""

    def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        tool_executor: Callable[[str, dict], str] | None = None,
    ) -> str:
        """Send a message list and return the assistant reply as a string.

        If *tools* and *tool_executor* are provided the implementation should
        run a tool-call loop: execute tool calls returned by the model and
        feed results back until the model returns a plain text reply.
        """
        ...


class OllamaProvider:
    """Ollama local REST API provider.

    Swap this out for any class that implements AIProvider.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        tool_executor: Callable[[str, dict], str] | None = None,
    ) -> str:
        try:
            return self._chat_with_tools(messages, model, tools, tool_executor)
        except _ToolsNotSupported:
            # Model doesn't support tool calling — retry without tools.
            return self._chat_with_tools(messages, model, None, None)

    def _chat_with_tools(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None,
        tool_executor: Callable[[str, dict], str] | None,
    ) -> str:
        conversation = list(messages)
        for _ in range(10):  # max tool-call rounds
            payload: dict = {"model": model, "messages": conversation, "stream": False}
            if tools:
                payload["tools"] = tools

            data = self._post(payload)
            msg = data.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls or tool_executor is None:
                return msg.get("content") or ""

            # Append the assistant's tool-call message
            conversation.append({"role": "assistant", "tool_calls": tool_calls})

            # Execute each tool and append results
            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result = tool_executor(name, args)
                conversation.append({"role": "tool", "content": result})

        # Exceeded max rounds — do a final plain call
        return (
            self._post({"model": model, "messages": conversation, "stream": False})[
                "message"
            ].get("content")
            or ""
        )

    def _post(self, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
                return body
        except urllib.error.HTTPError as exc:
            # Ollama returns 400 when the model doesn't support tools.
            msg = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code == 400 and "tool" in msg.lower():
                raise _ToolsNotSupported() from exc
            raise ConnectionError(
                f"Ollama error {exc.code} at {self.base_url}: {msg}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(
                f"Ollama not reachable at {self.base_url}: {exc}"
            ) from exc


class _ToolsNotSupported(Exception):
    """Raised internally when Ollama signals the model doesn't support tools."""
