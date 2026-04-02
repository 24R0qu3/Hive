"""Lightweight agent definitions, runner, and loader."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


def _extract_text_tool_calls(text: str) -> list[dict]:
    """Parse tool calls that a model emitted as raw JSON text instead of structured calls.

    Matches objects of the form ``{"name": "...", "arguments": {...}}`` anywhere
    in the text.  Returns a list in the same format as Ollama's ``tool_calls``.
    """
    calls = []
    for m in re.finditer(r'\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*"arguments"\s*:\s*(\{[^}]*\})', text, re.DOTALL):
        try:
            args = json.loads(m.group(2))
            calls.append({"function": {"name": m.group(1), "arguments": args}})
        except json.JSONDecodeError:
            continue
    return calls


@dataclass
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    tools: list[str] | None = None  # None = all tools; list = whitelist by name
    max_steps: int = 10
    stop_phrase: str = "TASK_COMPLETE"
    scope: str = "local"  # "local" | "global" | "builtin" — not persisted

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "max_steps": self.max_steps,
            "stop_phrase": self.stop_phrase,
        }

    @classmethod
    def from_dict(cls, d: dict, scope: str = "local") -> "AgentDefinition":
        return cls(
            name=d["name"],
            description=d["description"],
            system_prompt=d["system_prompt"],
            tools=d.get("tools"),
            max_steps=int(d.get("max_steps", 10)),
            stop_phrase=d.get("stop_phrase", "TASK_COMPLETE"),
            scope=scope,
        )


@dataclass
class AgentStep:
    step_num: int
    text: str = ""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_result: str = ""
    final: bool = False


@dataclass
class AgentResult:
    success: bool
    summary: str
    steps_taken: int


class AgentRunner:
    """Runs an agent loop: plan → tool call → observe → repeat."""

    def __init__(self, provider, model: str) -> None:
        self._provider = provider
        self._model = model

    def run(
        self,
        definition: AgentDefinition,
        goal: str,
        tool_executor: Callable[[str, dict], str],
        on_step: Callable[[AgentStep], None],
        all_tools: list[dict],
        abort_event: threading.Event,
    ) -> AgentResult:
        # Filter to agent's allowed tools if specified
        if definition.tools is not None:
            allowed = set(definition.tools)
            filtered_tools: list[dict] | None = [
                t for t in all_tools if t.get("function", {}).get("name", "") in allowed
            ]
        else:
            filtered_tools = all_tools or None

        messages: list[dict] = [
            {"role": "system", "content": definition.system_prompt},
            {"role": "user", "content": goal},
        ]
        text_mode: bool | None = None  # None = not yet determined

        for step_num in range(1, definition.max_steps + 1):
            if abort_event.is_set():
                return AgentResult(
                    success=False,
                    summary="Aborted by user.",
                    steps_taken=step_num - 1,
                )

            try:
                text, tool_calls = self._provider.chat_step(
                    messages, self._model, filtered_tools, abort_event
                )
            except Exception as exc:
                return AgentResult(
                    success=False,
                    summary=f"Error: {exc}",
                    steps_taken=step_num,
                )

            # Fallback: some models emit tool calls as raw JSON text instead of
            # using the structured tool_calls field.  Parse them out if present.
            # text_mode is locked after the first tool call to keep history consistent.
            if not tool_calls and text:
                parsed = _extract_text_tool_calls(text)
                if parsed:
                    tool_calls = parsed
                    if text_mode is None:
                        text_mode = True
            elif tool_calls and text_mode is None:
                text_mode = False

            # Stop if the model signals completion or returns no tool calls
            if definition.stop_phrase in text or not tool_calls:
                on_step(AgentStep(step_num=step_num, text=text, final=True))
                return AgentResult(
                    success=True,
                    summary=text,
                    steps_taken=step_num,
                )

            # Show any intermediate thinking text the model returned
            if text and not text_mode:  # text_mode=None treated as False here
                on_step(AgentStep(step_num=step_num, text=text))

            # Execute each tool call and append results to the conversation.
            # text_mode: model doesn't support structured tool_calls in history —
            # use plain user messages so it can follow the conversation.
            if text_mode:
                messages.append({"role": "assistant", "content": text})
            else:
                messages.append({"role": "assistant", "tool_calls": tool_calls})

            tool_results: list[str] = []
            for call in tool_calls:
                if abort_event.is_set():
                    return AgentResult(
                        success=False,
                        summary="Aborted by user.",
                        steps_taken=step_num,
                    )
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                on_step(AgentStep(step_num=step_num, tool_name=name, tool_args=args))
                result = tool_executor(name, args)
                on_step(
                    AgentStep(
                        step_num=step_num,
                        tool_name=name,
                        tool_args=args,
                        tool_result=result,
                    )
                )
                if text_mode:
                    tool_results.append(f"Result of {name}: {result}")
                else:
                    messages.append({"role": "tool", "content": result})

            if text_mode:
                messages.append({"role": "user", "content": "\n".join(tool_results)})

        return AgentResult(
            success=False,
            summary="Maximum steps reached without completing the goal.",
            steps_taken=definition.max_steps,
        )


def load_agent_definitions(cwd: Path) -> dict[str, AgentDefinition]:
    """Return all agents: built-ins < global < local (later overrides by name)."""
    from hive.agents import BUILTIN_AGENTS
    from hive.workspace import get_agent_configs, get_global_agent_configs

    definitions: dict[str, AgentDefinition] = {
        a.name: AgentDefinition.from_dict(a.to_dict(), scope="builtin")
        for a in BUILTIN_AGENTS
    }

    for config in get_global_agent_configs():
        try:
            defn = AgentDefinition.from_dict(config, scope="global")
            definitions[defn.name] = defn
        except (KeyError, ValueError, TypeError):
            pass

    for config in get_agent_configs(cwd):
        try:
            defn = AgentDefinition.from_dict(config, scope="local")
            definitions[defn.name] = defn
        except (KeyError, ValueError, TypeError):
            pass

    return definitions
