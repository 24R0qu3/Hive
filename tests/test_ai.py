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
