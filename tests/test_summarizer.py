"""Tests for hive.summarizer.RollingSummarizer."""

import threading
from unittest.mock import MagicMock

from hive.summarizer import SUMMARY_PREFIX, RollingSummarizer


def make_summarizer(token_limit=100, reply="summary text"):
    provider = MagicMock()
    provider.chat.return_value = reply
    return RollingSummarizer(provider, "test-model", token_limit), provider


def test_token_count_empty():
    assert RollingSummarizer.token_count([]) == 0


def test_token_count_uses_char_div_4():
    msgs = [{"role": "user", "content": "abcd"}]  # 4 chars -> 1 token
    assert RollingSummarizer.token_count(msgs) == 1


def test_token_count_handles_none_content():
    msgs = [{"role": "user", "content": None}]
    assert RollingSummarizer.token_count(msgs) == 0


def test_needs_summarization_false_under_limit():
    s, _ = make_summarizer(token_limit=1000)
    pairs = [{"role": "user", "content": "hi"}]
    assert not s.needs_summarization(pairs)


def test_needs_summarization_true_over_limit():
    s, _ = make_summarizer(token_limit=0)
    pairs = [{"role": "user", "content": "hi there"}]
    assert s.needs_summarization(pairs)


def test_summarize_sync_calls_provider():
    s, provider = make_summarizer()
    result = s.summarize_sync(None, [{"role": "user", "content": "hello"}])
    assert result == "summary text"
    provider.chat.assert_called_once()


def test_summarize_sync_includes_previous_summary():
    s, provider = make_summarizer()
    s.summarize_sync("old summary", [{"role": "user", "content": "hello"}])
    msgs_passed = provider.chat.call_args[0][0]
    assert msgs_passed[0] == {"role": "system", "content": "old summary"}


def test_summarize_sync_omits_summary_when_none():
    s, provider = make_summarizer()
    s.summarize_sync(None, [{"role": "user", "content": "hello"}])
    msgs_passed = provider.chat.call_args[0][0]
    assert msgs_passed[0]["role"] != "system" or "summary" not in msgs_passed[0].get(
        "content", ""
    )


def test_try_summarize_background_calls_on_done():
    s, _ = make_summarizer(reply="bg summary")
    done_event = threading.Event()
    result = []

    def on_done(new_conv):
        result.append(new_conv)
        done_event.set()

    s.try_summarize_background(None, [{"role": "user", "content": "hi"}], on_done)
    assert done_event.wait(timeout=5)
    assert len(result) == 1
    assert result[0][0]["role"] == "system"
    assert SUMMARY_PREFIX in result[0][0]["content"]


def test_try_summarize_background_skips_when_busy():
    s, _ = make_summarizer()
    s._busy.set()  # simulate in-progress
    called = []
    s.try_summarize_background(None, [], lambda c: called.append(c))
    import time

    time.sleep(0.1)
    assert called == []
    s._busy.clear()


def test_try_summarize_background_does_not_propagate_exception():
    provider = MagicMock()
    provider.chat.side_effect = RuntimeError("boom")
    s = RollingSummarizer(provider, "model", 100)
    done_event = threading.Event()
    called = []

    def on_done(c):
        called.append(c)
        done_event.set()

    s.try_summarize_background(None, [{"role": "user", "content": "x" * 500}], on_done)
    # Wait a bit — on_done should NOT be called
    done_event.wait(timeout=1)
    assert called == []
    # busy should be cleared even after exception
    assert not s.is_busy


def test_is_busy_false_initially():
    s, _ = make_summarizer()
    assert not s.is_busy
