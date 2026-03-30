"""AI provider interface and built-in Ollama implementation."""

from __future__ import annotations

import json
import threading
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


class _Aborted(Exception):
    """Raised when an in-flight AI request is cancelled by the user."""


@runtime_checkable
class AIProvider(Protocol):
    """Minimal interface every AI backend must satisfy."""

    def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        tool_executor: Callable[[str, dict], str] | None = None,
        abort: threading.Event | None = None,
    ) -> tuple[str, bool]:
        """Send a message list and return the assistant reply as a string.

        If *tools* and *tool_executor* are provided the implementation should
        run a tool-call loop: execute tool calls returned by the model and
        feed results back until the model returns a plain text reply.

        If *abort* is set while the request is in flight, ``_Aborted`` is raised.
        """
        ...


DEFAULT_NUM_CTX = 8192


class OllamaProvider:
    """Ollama local REST API provider.

    Swap this out for any class that implements AIProvider.
    """

    def __init__(
        self, base_url: str = DEFAULT_BASE_URL, num_ctx: int = DEFAULT_NUM_CTX
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.num_ctx = num_ctx

    def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        tool_executor: Callable[[str, dict], str] | None = None,
        abort: threading.Event | None = None,
    ) -> tuple[str, bool]:
        """Send *messages* to Ollama and return ``(reply, fallback)``.

        *fallback* is ``True`` when the model does not support tool calling and
        the request was retried without tools; ``False`` otherwise.
        Raises ``_Aborted`` if *abort* is set while waiting.
        """
        try:
            return (
                self._chat_with_tools(messages, model, tools, tool_executor, abort),
                False,
            )
        except _ToolsNotSupported:
            return (
                self._chat_with_tools(messages, model, None, None, abort),
                True,
            )

    def _chat_with_tools(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None,
        tool_executor: Callable[[str, dict], str] | None,
        abort: threading.Event | None = None,
    ) -> str:
        conversation = list(messages)
        for _ in range(10):  # max tool-call rounds
            if abort is not None and abort.is_set():
                raise _Aborted()
            payload: dict = {
                "model": model,
                "messages": conversation,
                "stream": False,
                "options": {"num_ctx": self.num_ctx},
            }
            if tools:
                payload["tools"] = tools

            data = self._post(payload, abort=abort)
            msg = data.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls or tool_executor is None:
                return msg.get("content") or ""

            # Append the assistant's tool-call message
            conversation.append({"role": "assistant", "tool_calls": tool_calls})

            # Execute each tool and append results
            for call in tool_calls:
                if abort is not None and abort.is_set():
                    raise _Aborted()
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
            self._post(
                {
                    "model": model,
                    "messages": conversation,
                    "stream": False,
                    "options": {"num_ctx": self.num_ctx},
                },
                abort=abort,
            )["message"].get("content")
            or ""
        )

    def _post(self, payload: dict, abort: threading.Event | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        _result: list[dict | None] = [None]
        _exc: list[BaseException | None] = [None]

        def _do() -> None:
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    _result[0] = json.loads(resp.read())
            except BaseException as e:  # noqa: BLE001
                _exc[0] = e

        t = threading.Thread(target=_do, daemon=True)
        t.start()
        while t.is_alive():
            t.join(timeout=0.3)
            if abort is not None and abort.is_set():
                raise _Aborted()

        exc = _exc[0]
        if exc is not None:
            if isinstance(exc, urllib.error.HTTPError):
                msg = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                # Ollama returns 400 for unsupported tools, but some models crash
                # with 500 when a tools payload is sent to a model without a tool
                # template (e.g. qwen3.5). Treat both as tools-not-supported so the
                # caller can retry without tools.
                if exc.code == 400 and "tool" in msg.lower():
                    raise _ToolsNotSupported() from exc
                if exc.code == 500 and (
                    "model runner" in msg.lower()
                    or "resource limit" in msg.lower()
                    or "unexpectedly stopped" in msg.lower()
                ):
                    raise _ToolsNotSupported() from exc
                raise ConnectionError(
                    f"Ollama error {exc.code} at {self.base_url}: {msg}"
                ) from exc
            if isinstance(exc, urllib.error.URLError):
                raise ConnectionError(
                    f"Ollama not reachable at {self.base_url}: {exc}"
                ) from exc
            raise exc
        return _result[0]  # type: ignore[return-value]

    def chat_step(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> tuple[str, list[dict]]:
        """Make exactly ONE model call and return ``(text, tool_calls)``.

        Does NOT execute tools and does NOT loop.  If the model rejects the
        tools payload, the call is retried without tools and an empty list is
        returned for *tool_calls*.
        """
        try:
            return self._chat_step_raw(messages, model, tools)
        except _ToolsNotSupported:
            text, _ = self._chat_step_raw(messages, model, None)
            return text, []

    def _chat_step_raw(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None,
    ) -> tuple[str, list[dict]]:
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": self.num_ctx},
        }
        if tools:
            payload["tools"] = tools
        data = self._post(payload)
        msg = data.get("message", {})
        tool_calls = msg.get("tool_calls") or []
        return msg.get("content") or "", tool_calls

    def is_reachable(self) -> bool:
        """Return True if Ollama is running and responding within 2 seconds."""
        req = urllib.request.Request(
            f"{self.base_url}/api/tags",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=2):
                return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Return model names available in Ollama, sorted alphabetically.

        Returns an empty list if Ollama is unreachable or returns an error.
        """
        req = urllib.request.Request(
            f"{self.base_url}/api/tags",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                return sorted(m["name"] for m in body.get("models", []))
        except Exception:
            return []


DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"

_ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]


def _openai_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI-format tool schemas to Anthropic tool format."""
    out = []
    for t in tools:
        fn = t.get("function", {})
        out.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            }
        )
    return out


def _openai_messages_to_anthropic(
    messages: list[dict],
) -> tuple[str | None, list[dict]]:
    """Convert OpenAI-format messages to Anthropic API format.

    Returns ``(system_content, anthropic_messages)``.  Tool calls are matched
    with their results by position within each assistant turn.
    """
    system: str | None = None
    result: list[dict] = []
    pending_ids: list[str] = []  # tool_use ids waiting for tool result messages

    for msg in messages:
        role = msg.get("role")

        if role == "system":
            system = msg.get("content", "")
            continue

        if role == "user":
            content = msg.get("content", "")
            result.append({"role": "user", "content": content})
            pending_ids = []

        elif role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            blocks: list[dict] = []
            pending_ids = []

            text = msg.get("content") or ""
            if text:
                blocks.append({"type": "text", "text": text})

            for i, call in enumerate(tool_calls):
                fn = call.get("function", {})
                tool_id = call.get("id") or f"hive_{i}"
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": fn.get("name", ""),
                        "input": args,
                    }
                )
                pending_ids.append(tool_id)

            if blocks:
                result.append({"role": "assistant", "content": blocks})

        elif role == "tool":
            # Tool results must go into a user message as tool_result blocks.
            tool_id = pending_ids.pop(0) if pending_ids else "hive_0"
            block = {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": msg.get("content", ""),
            }
            # Append to the last user message if it already holds tool_results,
            # otherwise open a new user message.
            if (
                result
                and result[-1]["role"] == "user"
                and isinstance(result[-1]["content"], list)
            ):
                result[-1]["content"].append(block)
            else:
                result.append({"role": "user", "content": [block]})

    return system, result


class AnthropicProvider:
    """Claude API provider via the official Anthropic SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        import os

        import anthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Export the variable or pass api_key= to AnthropicProvider."
            )
        self._client = anthropic.Anthropic(api_key=key)

    def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        tool_executor: Callable[[str, dict], str] | None = None,
        abort: threading.Event | None = None,
    ) -> tuple[str, bool]:
        conversation = list(messages)
        anthropic_tools = _openai_tools_to_anthropic(tools) if tools else []

        text = ""
        for _ in range(10):
            if abort is not None and abort.is_set():
                raise _Aborted()

            system, anth_msgs = _openai_messages_to_anthropic(conversation)
            kwargs: dict = {
                "model": model,
                "max_tokens": 8096,
                "messages": anth_msgs,
            }
            if system:
                kwargs["system"] = system
            if anthropic_tools:
                kwargs["tools"] = anthropic_tools

            # Run the blocking API call in a thread so abort can interrupt it
            _response: list = [None]
            _exc: list[BaseException | None] = [None]

            def _do_create() -> None:
                try:
                    _response[0] = self._client.messages.create(**kwargs)
                except BaseException as e:  # noqa: BLE001
                    _exc[0] = e

            t = threading.Thread(target=_do_create, daemon=True)
            t.start()
            while t.is_alive():
                t.join(timeout=0.3)
                if abort is not None and abort.is_set():
                    raise _Aborted()

            if _exc[0] is not None:
                raise _exc[0]  # type: ignore[misc]
            response = _response[0]

            text = ""
            tool_calls: list[dict] = []
            for block in response.content:
                if block.type == "text":
                    text = block.text
                elif block.type == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.id,
                            "function": {"name": block.name, "arguments": block.input},
                        }
                    )

            if not tool_calls or tool_executor is None:
                return text, False

            conversation.append({"role": "assistant", "tool_calls": tool_calls})
            for call in tool_calls:
                if abort is not None and abort.is_set():
                    raise _Aborted()
                fn = call["function"]
                result = tool_executor(fn["name"], fn["arguments"])
                conversation.append({"role": "tool", "content": result})

        # Max rounds exceeded — return last text
        return text, False

    def chat_step(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> tuple[str, list[dict]]:
        """Single model call; returns ``(text, tool_calls)`` in OpenAI format."""
        system, anth_msgs = _openai_messages_to_anthropic(messages)
        kwargs: dict = {
            "model": model,
            "max_tokens": 8096,
            "messages": anth_msgs,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _openai_tools_to_anthropic(tools)

        response = self._client.messages.create(**kwargs)

        text = ""
        tool_calls: list[dict] = []
        for block in response.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "function": {"name": block.name, "arguments": block.input},
                    }
                )

        return text, tool_calls

    def is_reachable(self) -> bool:
        """Always True for Anthropic — connectivity is assumed if key is set."""
        return True

    def list_models(self) -> list[str]:
        """Return the list of known Claude models."""
        return list(_ANTHROPIC_MODELS)


class _ToolsNotSupported(Exception):
    """Raised internally when Ollama signals the model doesn't support tools."""
