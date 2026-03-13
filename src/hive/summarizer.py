"""Rolling conversation summarizer for Hive's AI working memory.

When the token budget of the recent-message window is exceeded, a background
thread asks the AI provider to compress the conversation into a short summary.
The summary is stored as a leading system message in the working-memory list so
that subsequent AI calls retain key context without blowing up the context
window.
"""

import threading
from typing import Callable

from hive.ai import AIProvider

#: Prompt appended to the conversation when requesting a summary.
_SUMMARIZE_PROMPT = (
    "Summarize the conversation below in 3-5 sentences. "
    "Focus on key decisions, context, and what was discussed. "
    "This summary will be used to continue the conversation."
)

#: Prefix used to identify summary system messages.
SUMMARY_PREFIX = "Previous conversation summary: "


class RollingSummarizer:
    """Manages rolling AI summarization of the conversation working memory.

    The summarizer tracks recent message pairs (user+assistant turns) and
    triggers a background AI call to compress them when the token budget is
    exceeded.  The caller retains two separate lists:

    - ``_conversation``: AI working memory = ``[summary_system_msg] + recent_pairs``
    - ``_full_conversation``: complete raw history, never modified here

    Only ``_conversation`` is passed to this class.
    """

    def __init__(self, provider: AIProvider, model: str, token_limit: int) -> None:
        self._provider = provider
        self._model = model
        self._token_limit = token_limit
        self._busy = threading.Event()  # set while a summarization is in flight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def token_count(messages: list[dict]) -> int:
        """Approximate token count: total content chars // 4."""
        return sum(len(m.get("content") or "") for m in messages) // 4

    def needs_summarization(self, recent_pairs: list[dict]) -> bool:
        """True when *recent_pairs* (excluding any leading summary msg) exceed the budget."""
        return self.token_count(recent_pairs) > self._token_limit

    def summarize_sync(
        self,
        current_summary: str | None,
        recent_pairs: list[dict],
    ) -> str:
        """Run summarization synchronously.

        Returns the new summary text, or raises on failure.
        """
        msgs: list[dict] = []
        if current_summary:
            msgs.append({"role": "system", "content": current_summary})
        msgs.extend(recent_pairs)
        msgs.append({"role": "user", "content": _SUMMARIZE_PROMPT})
        return self._provider.chat(msgs, self._model)

    def try_summarize_background(
        self,
        current_summary: str | None,
        recent_pairs: list[dict],
        on_done: Callable[[list[dict]], None],
    ) -> None:
        """Fire-and-forget background summarization.

        Skips silently if a summarization is already in progress.
        Calls ``on_done(new_conversation)`` from the background thread when
        finished, where ``new_conversation`` is the new ``_conversation`` list
        (a single summary system message).  On failure, ``on_done`` is NOT
        called and the raw pairs are preserved by the caller.
        """
        if self._busy.is_set():
            return

        self._busy.set()

        def _run() -> None:
            try:
                text = self.summarize_sync(current_summary, recent_pairs)
                new_conv = [
                    {
                        "role": "system",
                        "content": f"{SUMMARY_PREFIX}{text}",
                    }
                ]
                on_done(new_conv)
            except Exception:
                pass  # keep raw pairs; retry next interval
            finally:
                self._busy.clear()

        threading.Thread(target=_run, daemon=True).start()

    @property
    def is_busy(self) -> bool:
        """True while a background summarization thread is running."""
        return self._busy.is_set()
