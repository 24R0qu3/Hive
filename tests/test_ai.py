"""Tests for hive.ai — provider interface and Ollama implementation."""

import json
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
        result = provider.chat([{"role": "user", "content": "hi"}], "llama3.2")
    assert result == "Hello!"


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
        result = provider.chat([], "mistral", tools=[], tool_executor=executor)

    assert result == "Here are the commands."
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
        result = provider.chat(
            [],
            "mistral",
            tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
            tool_executor=lambda n, a: "x",
        )

    assert result == "fallback reply"
    assert call_count[0] == 2  # first with tools (failed), second without
