"""Tests for hive.ai — provider interface and Ollama implementation."""

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from hive.ai import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    THINKING_MSGS,
    AIProvider,
    OllamaProvider,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_default_model_is_string():
    assert isinstance(DEFAULT_MODEL, str) and DEFAULT_MODEL


def test_default_base_url_starts_with_http():
    assert DEFAULT_BASE_URL.startswith("http")


def test_thinking_msgs_is_non_empty_list():
    assert isinstance(THINKING_MSGS, list) and len(THINKING_MSGS) > 0


def test_thinking_msgs_are_strings():
    for msg in THINKING_MSGS:
        assert isinstance(msg, str) and msg


# ---------------------------------------------------------------------------
# AIProvider Protocol
# ---------------------------------------------------------------------------


def test_ollama_provider_satisfies_protocol():
    assert isinstance(OllamaProvider(), AIProvider)


def test_custom_class_satisfies_protocol():
    class MyProvider:
        def chat(self, messages: list, model: str) -> str:
            return "hello"

    assert isinstance(MyProvider(), AIProvider)


# ---------------------------------------------------------------------------
# OllamaProvider.__init__
# ---------------------------------------------------------------------------


def test_default_base_url():
    p = OllamaProvider()
    assert p.base_url == DEFAULT_BASE_URL.rstrip("/")


def test_custom_base_url():
    p = OllamaProvider("http://example.com:11434/")
    assert p.base_url == "http://example.com:11434"


# ---------------------------------------------------------------------------
# OllamaProvider.chat — mocked HTTP
# ---------------------------------------------------------------------------


def _fake_response(content: str):
    """Build a mock urlopen context manager that returns an Ollama-style response."""
    body = json.dumps({"message": {"role": "assistant", "content": content}}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body
    return mock_resp


def test_chat_returns_assistant_content():
    provider = OllamaProvider()
    with patch("urllib.request.urlopen", return_value=_fake_response("Hello!")):
        result, tools_unsupported = provider.chat(
            [{"role": "user", "content": "hi"}], "llama3.2"
        )
    assert result == "Hello!"
    assert tools_unsupported is False


def test_chat_sends_correct_model():
    provider = OllamaProvider()
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return _fake_response("ok")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.chat([], "mistral")

    assert captured["body"]["model"] == "mistral"


def test_chat_sends_messages():
    provider = OllamaProvider()
    messages = [{"role": "user", "content": "ping"}]
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return _fake_response("pong")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.chat(messages, "llama3.2")

    assert captured["body"]["messages"] == messages


def test_chat_sends_stream_false():
    provider = OllamaProvider()
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return _fake_response("ok")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.chat([], "llama3.2")

    assert captured["body"]["stream"] is False


def test_chat_uses_correct_endpoint():
    provider = OllamaProvider("http://myhost:11434")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _fake_response("ok")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.chat([], "llama3.2")

    assert captured["url"] == "http://myhost:11434/api/chat"


def test_chat_raises_connection_error_on_url_error():
    import urllib.error

    provider = OllamaProvider()
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        with pytest.raises(ConnectionError, match="Ollama not reachable"):
            provider.chat([], "llama3.2")


# ---------------------------------------------------------------------------
# Tool-call loop
# ---------------------------------------------------------------------------


def _fake_tool_call_response(tool_name: str, arguments: dict):
    """Return a mock response with a single tool_call."""
    body = json.dumps(
        {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"function": {"name": tool_name, "arguments": arguments}}
                ],
            }
        }
    ).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body
    return mock_resp


def test_chat_with_tools_sends_tools_in_payload():
    provider = OllamaProvider()
    tools = [{"type": "function", "function": {"name": "ping", "parameters": {}}}]
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return _fake_response("ok")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.chat([], "mistral", tools=tools)

    assert "tools" in captured["body"]
    assert captured["body"]["tools"] == tools


def test_chat_tool_call_loop_executes_tool_and_returns_final_reply():
    provider = OllamaProvider()
    responses = iter(
        [
            _fake_tool_call_response("list_commands", {}),
            _fake_response("Here are the commands."),
        ]
    )

    def fake_urlopen(req, timeout=None):
        return next(responses)

    calls: list[tuple[str, dict]] = []

    def executor(name: str, args: dict) -> str:
        calls.append((name, args))
        return "result"

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result, tools_unsupported = provider.chat(
            [], "mistral", tools=[], tool_executor=executor
        )

    assert result == "Here are the commands."
    assert tools_unsupported is False
    assert calls == [("list_commands", {})]


def test_chat_tool_call_appends_tool_result_to_conversation():
    provider = OllamaProvider()
    sent_messages: list[list] = []
    responses = iter(
        [
            _fake_tool_call_response("get_info", {"name": "/exit"}),
            _fake_response("Done."),
        ]
    )

    def fake_urlopen(req, timeout=None):
        sent_messages.append(json.loads(req.data)["messages"])
        return next(responses)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.chat(
            [{"role": "user", "content": "hi"}],
            "mistral",
            tools=[],
            tool_executor=lambda n, a: "tool result",
        )

    # Second request should include the tool result message
    second_msgs = sent_messages[1]
    roles = [m["role"] for m in second_msgs]
    assert "tool" in roles
    tool_msg = next(m for m in second_msgs if m["role"] == "tool")
    assert tool_msg["content"] == "tool result"


def test_chat_falls_back_silently_on_tools_not_supported():
    """If Ollama returns 400 with 'tool' in body, retry without tools."""
    import urllib.error

    provider = OllamaProvider()
    call_count = [0]

    import io

    http_err = urllib.error.HTTPError(
        url="http://localhost:11434/api/chat",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"model does not support tools"}'),
    )

    def fake_urlopen(req, timeout=None):
        call_count[0] += 1
        body = json.loads(req.data)
        if "tools" in body:
            raise http_err
        return _fake_response("fallback reply")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result, tools_unsupported = provider.chat(
            [],
            "mistral",
            tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
            tool_executor=lambda n, a: "x",
        )

    assert result == "fallback reply"
    assert tools_unsupported is True
    assert call_count[0] == 2  # first with tools (failed), second without


# ---------------------------------------------------------------------------
# OllamaProvider.is_reachable
# ---------------------------------------------------------------------------


def test_is_reachable_returns_true_when_ollama_responds():
    provider = OllamaProvider()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert provider.is_reachable() is True


def test_is_reachable_returns_false_on_connection_error():
    provider = OllamaProvider()
    with patch("urllib.request.urlopen", side_effect=OSError("refused")):
        assert provider.is_reachable() is False


def test_is_reachable_returns_false_on_timeout():
    import socket

    provider = OllamaProvider()
    with patch("urllib.request.urlopen", side_effect=socket.timeout()):
        assert provider.is_reachable() is False


# ---------------------------------------------------------------------------
# _openai_messages_to_anthropic
# ---------------------------------------------------------------------------

from hive.ai import (  # noqa: E402
    _openai_messages_to_anthropic,
    _openai_tools_to_anthropic,
)


def test_system_message_extracted():
    msgs = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Hello"},
    ]
    system, anth = _openai_messages_to_anthropic(msgs)
    assert system == "Be helpful."
    assert anth[0]["role"] == "user"


def test_user_message_passthrough():
    msgs = [{"role": "user", "content": "Hi"}]
    _, anth = _openai_messages_to_anthropic(msgs)
    assert anth[0] == {"role": "user", "content": "Hi"}


def test_assistant_text_message():
    msgs = [{"role": "assistant", "content": "Sure!"}]
    _, anth = _openai_messages_to_anthropic(msgs)
    assert anth[0]["role"] == "assistant"
    assert anth[0]["content"][0] == {"type": "text", "text": "Sure!"}


def test_tool_call_converted_to_tool_use():
    msgs = [
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "shell", "arguments": {"command": "ls"}}}
            ],
        }
    ]
    _, anth = _openai_messages_to_anthropic(msgs)
    block = anth[0]["content"][0]
    assert block["type"] == "tool_use"
    assert block["name"] == "shell"
    assert block["input"] == {"command": "ls"}


def test_tool_result_becomes_user_message():
    msgs = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "tid1", "function": {"name": "shell", "arguments": {}}}
            ],
        },
        {"role": "tool", "content": "file.txt"},
    ]
    _, anth = _openai_messages_to_anthropic(msgs)
    user_msg = anth[1]
    assert user_msg["role"] == "user"
    assert user_msg["content"][0]["type"] == "tool_result"
    assert user_msg["content"][0]["tool_use_id"] == "tid1"
    assert user_msg["content"][0]["content"] == "file.txt"


def test_openai_tools_to_anthropic():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "shell",
                "description": "Run a command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                },
            },
        }
    ]
    anth = _openai_tools_to_anthropic(tools)
    assert anth[0]["name"] == "shell"
    assert anth[0]["description"] == "Run a command"
    assert "input_schema" in anth[0]


# ---------------------------------------------------------------------------
# AnthropicProvider
# ---------------------------------------------------------------------------

from hive.ai import AnthropicProvider  # noqa: E402


def test_anthropic_provider_requires_api_key():
    with patch.dict("os.environ", {}, clear=True):
        import os

        os.environ.pop("ANTHROPIC_API_KEY", None)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            AnthropicProvider()


def test_anthropic_provider_satisfies_protocol(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("anthropic.Anthropic"):
        provider = AnthropicProvider()
    assert isinstance(provider, AIProvider)


def test_anthropic_provider_is_reachable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("anthropic.Anthropic"):
        provider = AnthropicProvider()
    assert provider.is_reachable() is True


def test_anthropic_provider_list_models(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("anthropic.Anthropic"):
        provider = AnthropicProvider()
    models = provider.list_models()
    assert isinstance(models, list)
    assert len(models) > 0
    assert all(isinstance(m, str) for m in models)


def _make_anthropic_response(text: str = "", tool_calls: list | None = None):
    """Build a mock Anthropic messages.create response."""
    blocks = []
    if text:
        block = MagicMock()
        block.type = "text"
        block.text = text
        blocks.append(block)
    for tc in tool_calls or []:
        block = MagicMock()
        block.type = "tool_use"
        block.id = tc["id"]
        block.name = tc["name"]
        block.input = tc["input"]
        blocks.append(block)
    response = MagicMock()
    response.content = blocks
    return response


def test_anthropic_chat_returns_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("anthropic.Anthropic"):
        provider = AnthropicProvider()
        provider._client.messages.create.return_value = _make_anthropic_response(
            "Hello!"
        )
        result, fallback = provider.chat(
            [{"role": "user", "content": "hi"}], "claude-sonnet-4-6"
        )
    assert result == "Hello!"
    assert fallback is False


def test_anthropic_chat_step_returns_tool_calls(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("anthropic.Anthropic"):
        provider = AnthropicProvider()
        provider._client.messages.create.return_value = _make_anthropic_response(
            tool_calls=[{"id": "t1", "name": "shell", "input": {"command": "ls"}}]
        )
        text, tool_calls = provider.chat_step(
            [{"role": "user", "content": "run ls"}], "claude-sonnet-4-6"
        )
    assert text == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "shell"
    assert tool_calls[0]["function"]["arguments"] == {"command": "ls"}


def test_anthropic_chat_executes_tool_loop(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    call_count = [0]
    with patch("anthropic.Anthropic"):
        provider = AnthropicProvider()

        def side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_anthropic_response(
                    tool_calls=[
                        {"id": "t1", "name": "shell", "input": {"command": "ls"}}
                    ]
                )
            return _make_anthropic_response("Done!")

        provider._client.messages.create.side_effect = side_effect
        result, _ = provider.chat(
            [{"role": "user", "content": "run ls"}],
            "claude-sonnet-4-6",
            tools=[
                {
                    "type": "function",
                    "function": {"name": "shell", "description": "x", "parameters": {}},
                }
            ],
            tool_executor=lambda n, a: "file.txt",
        )
    assert result == "Done!"
    assert call_count[0] == 2


# ---------------------------------------------------------------------------
# OllamaProvider.chat_step — tools-not-supported behaviour


def test_chat_step_raises_tools_not_supported_when_tools_passed():
    """chat_step re-raises _ToolsNotSupported when tools were requested."""
    import io
    import urllib.error

    from hive.ai import _ToolsNotSupported

    provider = OllamaProvider()
    http_err = urllib.error.HTTPError(
        url="http://localhost:11434/api/chat",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"model does not support tools"}'),
    )
    tools = [{"type": "function", "function": {"name": "shell", "parameters": {}}}]

    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(_ToolsNotSupported):
            provider.chat_step([], "phi4-mini:3.8b", tools=tools)


def test_chat_step_falls_back_silently_when_no_tools():
    """chat_step falls back transparently when no tools were requested."""
    import io
    import urllib.error

    from hive.ai import _ToolsNotSupported

    provider = OllamaProvider()
    http_err = urllib.error.HTTPError(
        url="http://localhost:11434/api/chat",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"model does not support tools"}'),
    )
    call_count = [0]

    def fake_urlopen(req, timeout=None):
        call_count[0] += 1
        body = json.loads(req.data)
        if body.get("tools"):
            raise http_err
        return _fake_response("ok")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        text, tool_calls = provider.chat_step([], "phi4-mini:3.8b", tools=None)

    assert text == "ok"
    assert tool_calls == []


# ---------------------------------------------------------------------------
# OllamaProvider.chat_step — abort support
# ---------------------------------------------------------------------------


def test_ollama_chat_step_returns_text_and_empty_tool_calls():
    provider = OllamaProvider()
    with patch("urllib.request.urlopen", return_value=_fake_response("hi")):
        text, tool_calls = provider.chat_step(
            [{"role": "user", "content": "hello"}], "llama3.2"
        )
    assert text == "hi"
    assert tool_calls == []


def test_ollama_chat_step_returns_tool_calls():
    provider = OllamaProvider()
    with patch(
        "urllib.request.urlopen",
        return_value=_fake_tool_call_response("shell", {"command": "ls"}),
    ):
        text, tool_calls = provider.chat_step([], "llama3.2")
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "shell"


def test_ollama_chat_step_abort_pre_set_raises():
    """If abort is already set before the call, _Aborted should be raised."""
    from hive.ai import _Aborted

    provider = OllamaProvider()
    abort = threading.Event()
    abort.set()

    def slow_urlopen(req, timeout=None):
        time.sleep(10)  # should never be reached in meaningful time

    with patch("urllib.request.urlopen", side_effect=slow_urlopen):
        with pytest.raises(_Aborted):
            provider.chat_step([], "llama3.2", abort=abort)


def test_ollama_chat_step_abort_during_wait_raises():
    """Abort set while the HTTP request is in flight should raise _Aborted."""
    from hive.ai import _Aborted

    provider = OllamaProvider()
    abort = threading.Event()

    def slow_urlopen(req, timeout=None):
        time.sleep(2)
        return _fake_response("too late")

    # Set abort shortly after chat_step starts polling
    def _set_abort():
        time.sleep(0.1)
        abort.set()

    threading.Thread(target=_set_abort, daemon=True).start()

    with patch("urllib.request.urlopen", side_effect=slow_urlopen):
        with pytest.raises(_Aborted):
            provider.chat_step([], "llama3.2", abort=abort)


# ---------------------------------------------------------------------------
# AnthropicProvider.chat_step — abort support
# ---------------------------------------------------------------------------


def test_anthropic_chat_step_abort_pre_set_raises(monkeypatch):
    """Abort set before the call should raise _Aborted immediately."""
    from hive.ai import _Aborted

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    abort = threading.Event()
    abort.set()

    with patch("anthropic.Anthropic"):
        provider = AnthropicProvider()

        def slow_create(**kwargs):
            time.sleep(10)

        provider._client.messages.create.side_effect = slow_create

        with pytest.raises(_Aborted):
            provider.chat_step([], "claude-sonnet-4-6", abort=abort)


def test_anthropic_chat_step_abort_during_wait_raises(monkeypatch):
    """Abort set while the API call is in flight should raise _Aborted."""
    from hive.ai import _Aborted

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    abort = threading.Event()

    with patch("anthropic.Anthropic"):
        provider = AnthropicProvider()

        def slow_create(**kwargs):
            time.sleep(2)
            return _make_anthropic_response("too late")

        provider._client.messages.create.side_effect = slow_create

        def _set_abort():
            time.sleep(0.1)
            abort.set()

        threading.Thread(target=_set_abort, daemon=True).start()

        with pytest.raises(_Aborted):
            provider.chat_step([], "claude-sonnet-4-6", abort=abort)
