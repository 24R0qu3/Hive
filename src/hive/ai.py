"""AI provider interface and built-in Ollama implementation."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

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

    def chat(self, messages: list[dict], model: str) -> str:
        """Send a message list and return the assistant reply as a string."""
        ...


class OllamaProvider:
    """Ollama local REST API provider.

    Swap this out for any class that implements AIProvider.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def chat(self, messages: list[dict], model: str) -> str:
        payload = json.dumps(
            {"model": model, "messages": messages, "stream": False}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
                return data["message"]["content"]
        except urllib.error.URLError as exc:
            raise ConnectionError(
                f"Ollama not reachable at {self.base_url}: {exc}"
            ) from exc
