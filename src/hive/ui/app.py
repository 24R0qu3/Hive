import io
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.auto_suggest import Suggestion
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console
from rich.table import Table

from hive import ai
from hive.commands import AI_TOOLS, COMMAND_NAMES, SUB_COMMANDS, SYSTEM_PROMPT, run_tool
from hive.i18n import LANG_OPTIONS, t
from hive.log import add_session_handler
from hive.mcp import MCPManager, MCPServerConfig
from hive.summarizer import SUMMARY_PREFIX, RollingSummarizer
from hive.ui.history import HistoryManager
from hive.ui.panels import (
    build_language_panel,
    build_mcp_panel,
    build_model_panel,
    build_name_panel,
    build_resume_panel,
    build_trust_panel,
    build_welcome,
)
from hive.user import (
    get_user_name,
    get_warned_flags,
    has_user_name,
    set_user_name,
    set_warned_flag,
)
from hive.workspace import (
    DEFAULT_SUMMARIZATION_TOKEN_LIMIT,
    Session,
    create_workspace,
    get_global_mcp_configs,
    get_language,
    get_local_mcp_configs,
    get_mcp_configs,
    get_model,
    get_summarization_token_limit,
    has_language,
    list_sessions,
    load_conversation,
    load_full_conversation,
    load_output,
    new_session,
    save_agent_config,
    save_conversation,
    save_full_conversation,
    save_global_mcp_configs,
    save_mcp_configs,
    save_output,
    set_language,
    set_model,
    update_meta,
)

logger = logging.getLogger(__name__)


class _ScrollableWindow(Window):
    """Window subclass that routes scroll events to a caller-supplied handler.

    Overrides the private ``_mouse_handler`` method so that scroll events are
    handled by *on_scroll* while all other mouse events fall through to the
    default prompt_toolkit logic.  The override is explicit (a subclass method)
    rather than an instance monkey-patch, which means it survives pickling and
    is easier to reason about.  If prompt_toolkit ever renames the method the
    subclass will just inherit the default again — scroll won't work, but
    nothing will crash.
    """

    def __init__(self, *args, on_scroll=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_scroll = on_scroll

    def _mouse_handler(self, mouse_event: MouseEvent):  # type: ignore[override]
        if self._on_scroll and mouse_event.event_type in (
            MouseEventType.SCROLL_UP,
            MouseEventType.SCROLL_DOWN,
        ):
            return self._on_scroll(mouse_event)
        return super()._mouse_handler(mouse_event)


_STYLE = Style.from_dict(
    {
        "slash-cmd": "#FFC107 bold",
        "slash-sub": "#FFD54F bold",
        "hint": "#666666",
        "transient-hint": "#999999 italic",
    }
)


class _SlashLexer(Lexer):
    """Highlights slash-command tokens and their sub-commands in the input."""

    def lex_document(self, document):
        lines = document.lines

        def get_line(lineno):
            line = lines[lineno]
            parts = line.split(" ")
            fragments: list = []
            first_cmd: str | None = None
            for i, part in enumerate(parts):
                if i > 0:
                    fragments.append(("", " "))
                if (
                    i == 0
                    and part.startswith("/")
                    and any(cmd.startswith(part) for cmd in _COMMANDS)
                ):
                    fragments.append(("class:slash-cmd", part))
                    first_cmd = next((cmd for cmd in _COMMANDS if cmd == part), None)
                elif i == 1 and first_cmd and part in SUB_COMMANDS.get(first_cmd, []):
                    fragments.append(("class:slash-sub", part))
                else:
                    fragments.append(("", part))
            return fragments

        return get_line


# Bare command names from the registry — used for autocomplete and coloring.
_COMMANDS = COMMAND_NAMES

# Prompts for the /agent add wizard steps.
_AGENT_ADD_PROMPTS = [
    "Agent name (e.g. 'git-helper'):",
    "Short description:",
    "System prompt (use Ctrl+J for newlines):",
    "Allowed tools, comma-separated (empty = all tools):",
    "Max steps (default 10):",
    "Scope — 'local' (this project) or 'global' (all projects, default local):",
]


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class HiveApp:
    def __init__(
        self,
        cwd: Path,
        session: Session | None = None,
        trusted: bool = False,
        _output=None,  # for testing: pass a DummyOutput to avoid terminal detection
        provider: str | None = None,  # "ollama" | "anthropic" | None = auto-detect
    ):
        self._cwd = cwd

        # --- global user name ---
        self._user_name: str | None = get_user_name()
        self._awaiting_name: bool = not has_user_name()
        self._name_is_rename: bool = False
        self._name_panel_width: int = -1

        # Whether the trust dialog is needed (may be deferred until after name entry)
        self._needs_trust: bool = not trusted and session is None
        self._awaiting_trust: bool = not self._awaiting_name and self._needs_trust
        self._trust_choice: int = 0
        self._trust_panel_key: tuple = (-1, -1)

        # --- session setup ---
        if session is not None:
            self._session: Session | None = session
            add_session_handler(str(session.log_path))
        elif trusted:
            self._session = new_session(cwd)
            add_session_handler(str(self._session.log_path))
        else:
            self._session = None

        # --- language state ---
        workspace_exists = trusted or session is not None
        if workspace_exists:
            lang_code = get_language(cwd)
            self._lang: str = lang_code if lang_code else "en"
            # Show picker if language not yet set and not blocked behind name prompt
            self._picking_language: bool = (
                not has_language(cwd) and not self._awaiting_name
            )
        else:
            self._lang = "en"
            self._picking_language = False
        self._lang_idx: int = 0
        self._lang_panel_key: tuple = (-1, -1)

        # --- resume picker state ---
        self._resuming: bool = False
        self._resume_sessions: list[Session] = []
        self._resume_idx: int = 0
        self._resume_panel_key: tuple = (-1, -1)

        # --- model picker state ---
        self._picking_model: bool = False
        self._model_list: list[str] = []
        self._model_idx: int = 0
        self._model_panel_key: tuple = (-1, -1)

        # --- hint state ---
        self._hint_idx: int = 0

        # --- AI state ---
        import os

        _use_anthropic = provider == "anthropic" or (
            provider is None and bool(os.environ.get("ANTHROPIC_API_KEY"))
        )
        if _use_anthropic:
            try:
                self._provider: ai.AIProvider = ai.AnthropicProvider()
                self._model: str = get_model(cwd) or ai.DEFAULT_ANTHROPIC_MODEL
            except RuntimeError:
                self._provider = ai.OllamaProvider()
                self._model = get_model(cwd) or ai.DEFAULT_MODEL
        else:
            self._provider = ai.OllamaProvider()
            self._model = get_model(cwd) or ai.DEFAULT_MODEL
        _sum_limit = (
            get_summarization_token_limit(cwd)
            if (trusted or session is not None)
            else DEFAULT_SUMMARIZATION_TOKEN_LIMIT
        )
        self._summarizer = RollingSummarizer(self._provider, self._model, _sum_limit)
        self._full_conversation: list[dict] = []
        self._conversation: list[dict] = []
        self._ai_thinking: bool = False
        self._last_ctrl_c: float = 0.0
        self._transient_hint: str = ""

        # --- MCP state ---
        self._mcp = MCPManager()

        # MCP management panel state
        self._managing_mcp: bool = False
        self._mcp_configs: list[MCPServerConfig] = []
        self._mcp_idx: int = 0
        self._mcp_panel_key: tuple = (-1, -1)
        self._mcp_confirm_delete: str | None = None
        self._mcp_reconnecting: set[str] = set()
        self._mcp_tools_unsupported_shown: bool = False
        self._active_mcp_servers: set[str] = set()

        # MCP add-server wizard state
        self._mcp_adding: bool = False
        self._mcp_add_step: int = 0  # 0=name, 1=command, 2=args, 3=env
        self._mcp_add_data: dict = {}

        # --- AI / agent abort state ---
        self._ai_abort: threading.Event | None = None
        self._agent_abort: threading.Event | None = None

        # Agent add wizard state
        self._agent_adding: bool = False
        self._agent_add_step: int = (
            0  # 0=name,1=description,2=system_prompt,3=tools,4=max_steps
        )
        self._agent_add_data: dict = {}

        # --- output state ---
        self._welcome_lines: list[str] = []
        self._welcome_width: int = -1
        self._welcome_mcp_key: tuple = ()
        self._output_lines: list[str] = []
        self._scroll_offset: int = 0

        if session is not None and session.output_path.exists():
            self._output_lines = load_output(session)

        if session is not None:
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_conv = ex.submit(load_conversation, session)
                f_full = ex.submit(load_full_conversation, session)
            self._conversation = f_conv.result()
            self._full_conversation = f_full.result()
            # Migration: seed full history from compact conversation if missing
            if not self._full_conversation and self._conversation:
                self._full_conversation = [
                    m for m in self._conversation if m.get("role") != "system"
                ]

        # --- history ---
        self._history = HistoryManager(
            self._session.history_path if self._session is not None else None
        )

        # --- input field ---
        self.input_field = TextArea(
            prompt="→ ",
            multiline=True,
            wrap_lines=True,
            scrollbar=False,
            lexer=_SlashLexer(),
            get_line_prefix=lambda lineno, wrap_count: (
                "  " if lineno > 0 or wrap_count > 0 else ""
            ),
        )

        def _update_suggestion(_buf=None) -> None:
            text = self.input_field.buffer.document.text
            self.input_field.buffer.suggestion = None
            if "\n" in text:
                return
            parts = text.split(" ", 1)
            first = parts[0]
            # Sub-command completion: "/cmd sub_prefix"
            if len(parts) == 2 and first in SUB_COMMANDS:
                sub_prefix = parts[1]
                subs = [
                    s
                    for s in SUB_COMMANDS[first]
                    if s.startswith(sub_prefix) and s != sub_prefix
                ]
                if subs:
                    self.input_field.buffer.suggestion = Suggestion(
                        subs[0][len(sub_prefix) :]
                    )
                return
            # Top-level command completion: "/cmd_prefix"
            last = text.rsplit(" ", 1)[-1]
            if len(last) > 1 and last.startswith("/"):
                matches = [c for c in _COMMANDS if c.startswith(last) and c != last]
                if matches:
                    self.input_field.buffer.suggestion = Suggestion(
                        matches[0][len(last) :]
                    )

        self.input_field.buffer.on_text_changed += _update_suggestion

        def get_input_height() -> int:
            try:
                from prompt_toolkit import get_app

                col = get_app().output.get_size().columns
            except Exception:
                col = shutil.get_terminal_size().columns
            available = max(1, col - 4)
            text = self.input_field.text or ""
            lines = text.split("\n") if text else [""]
            total = sum(
                max(1, (len(line) + available - 1) // available) for line in lines
            )
            return max(1, total)

        self.input_field.window.height = get_input_height

        # --- key bindings ---
        kb = KeyBindings()

        _name_active = Condition(lambda: self._awaiting_name)
        _trust_active = Condition(lambda: self._awaiting_trust)
        _lang_active = Condition(lambda: self._picking_language)
        _resume_active = Condition(lambda: self._resuming)

        # Blocks regular submit and history nav
        _not_modal = ~Condition(
            lambda: (
                self._awaiting_name
                or self._awaiting_trust
                or self._picking_language
                or self._resuming
                or self._picking_model
                or self._managing_mcp
                or self._agent_adding
            )
        )
        # Blocks history nav (but not name — user is typing freely there)
        _not_picker = ~Condition(
            lambda: (
                self._resuming
                or self._picking_language
                or self._picking_model
                or self._awaiting_name
                or self._managing_mcp
                or self._agent_adding
            )
        )

        # -- Name input: Enter saves name, transitions to next modal --
        @kb.add("enter", filter=has_focus(self.input_field) & _name_active, eager=True)
        def name_submit(event):
            name = self.input_field.text.strip()
            if not name:
                return  # name is required
            set_user_name(name)
            self._user_name = name
            self._name_is_rename = False
            self._awaiting_name = False
            self.input_field.text = ""
            self._name_panel_width = -1
            if self._needs_trust:
                self._awaiting_trust = True
            elif not has_language(self._cwd):
                self._picking_language = True
                self._lang_idx = 0
                self._lang_panel_key = (-1, -1)
            else:
                self._welcome_width = -1
            event.app.invalidate()

        # -- Regular submit --
        @kb.add("enter", filter=has_focus(self.input_field) & _not_modal, eager=True)
        def submit(event):
            if _hint_matches():
                return  # let tab_complete handle it
            text = self.input_field.text.strip()
            if self._ai_thinking:
                self.print(t("ai.busy", self._lang))
                return
            if text:
                self._history.append(text)
                self.input_field.text = ""
                self.handle_input(text)

        # -- Trust dialog: ← → to choose, Enter to confirm --
        @kb.add("left", filter=_trust_active, eager=True)
        def trust_left(event):
            self._trust_choice = 0
            self._trust_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("right", filter=_trust_active, eager=True)
        def trust_right(event):
            self._trust_choice = 1
            self._trust_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("enter", filter=_trust_active, eager=True)
        def trust_confirm(event):
            if self._trust_choice == 0:
                create_workspace(self._cwd)
                self._session = new_session(self._cwd)
                add_session_handler(str(self._session.log_path))
                self._history.path = self._session.history_path
                self._needs_trust = False
                self._awaiting_trust = False
                self._picking_language = True
                self._lang_idx = 0
                self._lang_panel_key = (-1, -1)
                event.app.invalidate()
            else:
                event.app.exit()

        # -- Language picker: ↑ ↓ to navigate, Enter to confirm --
        @kb.add("up", filter=_lang_active, eager=True)
        def lang_up(event):
            self._lang_idx = max(0, self._lang_idx - 1)
            self._lang_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("down", filter=_lang_active, eager=True)
        def lang_down(event):
            self._lang_idx = min(len(LANG_OPTIONS) - 1, self._lang_idx + 1)
            self._lang_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("enter", filter=_lang_active, eager=True)
        def lang_confirm(event):
            lang_code = LANG_OPTIONS[self._lang_idx][0]
            set_language(self._cwd, lang_code)
            self._lang = lang_code
            self._picking_language = False
            self._welcome_width = -1
            event.app.invalidate()

        # -- Resume picker: ↑ ↓ to navigate, Enter/Esc to confirm/cancel --
        _resume_normal = Condition(lambda: self._resuming)

        @kb.add("up", filter=_resume_normal, eager=True)
        def resume_up(event):
            self._resume_idx = max(0, self._resume_idx - 1)
            self._resume_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("down", filter=_resume_normal, eager=True)
        def resume_down(event):
            self._resume_idx = min(len(self._resume_sessions) - 1, self._resume_idx + 1)
            self._resume_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("enter", filter=_resume_normal, eager=True)
        def resume_confirm(event):
            self._load_session_inline(self._resume_sessions[self._resume_idx])
            self._resuming = False
            self._welcome_width = -1
            event.app.invalidate()

        @kb.add("escape", filter=_resume_normal, eager=True)
        @kb.add("c-c", filter=_resume_normal, eager=True)
        def resume_cancel(event):
            self._resuming = False
            self._welcome_width = -1
            event.app.invalidate()

        # -- Model picker: ↑ ↓ to navigate, Enter to select, Esc/Ctrl+C to cancel --
        _model_active = Condition(lambda: self._picking_model)

        @kb.add("up", filter=_model_active, eager=True)
        def model_up(event):
            self._model_idx = max(0, self._model_idx - 1)
            self._model_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("down", filter=_model_active, eager=True)
        def model_down(event):
            self._model_idx = min(len(self._model_list) - 1, self._model_idx + 1)
            self._model_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("enter", filter=_model_active, eager=True)
        def model_confirm(event):
            if self._model_list:
                chosen = self._model_list[self._model_idx]
                self._model = chosen
                if self._session:
                    set_model(self._cwd, chosen)
                self.print(t("model.set", self._lang).format(model=chosen))
            self._picking_model = False
            self._welcome_width = -1
            event.app.invalidate()

        @kb.add("escape", filter=_model_active, eager=True)
        @kb.add("c-c", filter=_model_active, eager=True)
        def model_cancel(event):
            self._picking_model = False
            self._welcome_width = -1
            event.app.invalidate()

        # -- MCP management panel --
        _mcp_active = Condition(lambda: self._managing_mcp and not self._mcp_adding)
        _mcp_adding_active = Condition(lambda: self._managing_mcp and self._mcp_adding)

        @kb.add("up", filter=_mcp_active, eager=True)
        def mcp_up(event):
            self._mcp_idx = max(0, self._mcp_idx - 1)
            self._mcp_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("down", filter=_mcp_active, eager=True)
        def mcp_down(event):
            self._mcp_idx = min(len(self._mcp_configs) - 1, self._mcp_idx + 1)
            self._mcp_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("enter", filter=_mcp_active, eager=True)
        def mcp_toggle(event):
            if not self._mcp_configs:
                return
            config = self._mcp_configs[self._mcp_idx]
            config.enabled = not config.enabled
            self._save_mcp_configs_all()
            if config.enabled:
                threading.Thread(
                    target=self._connect_mcp_server, args=(config,), daemon=True
                ).start()
                self.print(t("mcp.manage.enabled", self._lang).format(name=config.name))
            else:

                def _do_disable(name=config.name):
                    self._mcp.disconnect(name)
                    self._mcp_panel_key = (-1, -1)
                    if self.app.is_running:
                        self.app.invalidate()

                threading.Thread(target=_do_disable, daemon=True).start()
                self.print(
                    t("mcp.manage.disabled", self._lang).format(name=config.name)
                )
            self._mcp_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("r", filter=_mcp_active, eager=True)
        @kb.add("R", filter=_mcp_active, eager=True)
        def mcp_reconnect_selected(event):
            if not self._mcp_configs:
                return
            name = self._mcp_configs[self._mcp_idx].name
            self._mcp_reconnecting.add(name)
            self._mcp_panel_key = (-1, -1)
            self.print(t("mcp.manage.reconnecting", self._lang).format(name=name))

            def _do_reconnect():
                try:
                    self._mcp.reconnect(name)
                except Exception as exc:
                    logger.error("Manual MCP reconnect failed for '%s': %s", name, exc)
                finally:
                    self._mcp_reconnecting.discard(name)
                    self._mcp_panel_key = (-1, -1)
                    if self.app.is_running:
                        self.app.invalidate()

            threading.Thread(target=_do_reconnect, daemon=True).start()
            event.app.invalidate()

        @kb.add("d", filter=_mcp_active, eager=True)
        @kb.add("D", filter=_mcp_active, eager=True)
        def mcp_delete_or_confirm(event):
            if not self._mcp_configs:
                return
            name = self._mcp_configs[self._mcp_idx].name
            if self._mcp_confirm_delete != name:
                self._mcp_confirm_delete = name
                self._mcp_panel_key = (-1, -1)
                event.app.invalidate()
                return

            # Confirmed — delete
            def _do_delete(name=name):
                self._mcp.disconnect(name)
                self._mcp_panel_key = (-1, -1)
                if self.app.is_running:
                    self.app.invalidate()

            threading.Thread(target=_do_delete, daemon=True).start()
            self._mcp_configs = [c for c in self._mcp_configs if c.name != name]
            self._save_mcp_configs_all()
            self._mcp_idx = min(self._mcp_idx, max(0, len(self._mcp_configs) - 1))
            self._mcp_confirm_delete = None
            self._mcp_panel_key = (-1, -1)
            self.print(t("mcp.manage.deleted", self._lang).format(name=name))
            event.app.invalidate()

        @kb.add("escape", filter=_mcp_active, eager=True)
        def mcp_manage_escape(event):
            if self._mcp_confirm_delete is not None:
                self._mcp_confirm_delete = None
                self._mcp_panel_key = (-1, -1)
                event.app.invalidate()
                return
            self._managing_mcp = False
            self._welcome_width = -1
            event.app.invalidate()

        @kb.add("a", filter=_mcp_active, eager=True)
        @kb.add("A", filter=_mcp_active, eager=True)
        def mcp_add_start(event):
            self._mcp_adding = True
            self._mcp_add_step = 0
            self._mcp_add_data = {}
            self.input_field.text = ""
            self.print(t("mcp.manage.add.prompt_name", self._lang))
            event.app.invalidate()

        @kb.add(
            "enter", filter=has_focus(self.input_field) & _mcp_adding_active, eager=True
        )
        def mcp_add_step_submit(event):
            text = self.input_field.text.strip()
            step_keys = ["name", "command", "args", "env"]
            prompts = [
                "mcp.manage.add.prompt_name",
                "mcp.manage.add.prompt_command",
                "mcp.manage.add.prompt_args",
                "mcp.manage.add.prompt_env",
            ]
            self._mcp_add_data[step_keys[self._mcp_add_step]] = text
            self.input_field.text = ""
            self._mcp_add_step += 1
            if self._mcp_add_step < len(step_keys):
                self.print(t(prompts[self._mcp_add_step], self._lang))
                event.app.invalidate()
                return
            # All steps done — build config
            raw_args = (
                self._mcp_add_data.get("args", "").split()
                if self._mcp_add_data.get("args")
                else []
            )
            raw_env: dict[str, str] = {}
            for pair in (self._mcp_add_data.get("env", "") or "").split():
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    raw_env[k] = v
            new_config = MCPServerConfig(
                name=self._mcp_add_data["name"],
                command=self._mcp_add_data["command"],
                args=raw_args,
                env=raw_env,
            )
            self._mcp_configs.append(new_config)
            self._save_mcp_configs_all()
            threading.Thread(
                target=self._connect_mcp_server, args=(new_config,), daemon=True
            ).start()
            self._mcp_adding = False
            self._mcp_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add(
            "escape",
            filter=has_focus(self.input_field) & _mcp_adding_active,
            eager=True,
        )
        def mcp_add_cancel(event):
            self._mcp_adding = False
            self._mcp_add_step = 0
            self._mcp_add_data = {}
            self.input_field.text = ""
            event.app.invalidate()

        # -- Agent add wizard --
        _agent_adding_active = Condition(lambda: self._agent_adding)

        @kb.add(
            "enter",
            filter=has_focus(self.input_field) & _agent_adding_active,
            eager=True,
        )
        def agent_add_step_submit(event):
            text = self.input_field.text.strip()
            step_keys = [
                "name",
                "description",
                "system_prompt",
                "tools",
                "max_steps",
                "scope",
            ]
            self._agent_add_data[step_keys[self._agent_add_step]] = text
            self.input_field.text = ""
            self._agent_add_step += 1
            if self._agent_add_step < len(step_keys):
                self.print(_AGENT_ADD_PROMPTS[self._agent_add_step])
                event.app.invalidate()
                return
            # All steps done — build and save
            raw_tools_str = self._agent_add_data.get("tools", "").strip()
            raw_tools: list[str] | None = (
                [t.strip() for t in raw_tools_str.split(",") if t.strip()]
                if raw_tools_str
                else None
            )
            try:
                max_steps = int(self._agent_add_data.get("max_steps") or 10)
            except ValueError:
                max_steps = 10
            scope = self._agent_add_data.get("scope", "").strip().lower()
            if scope not in ("local", "global"):
                scope = "local"
            from hive.agent import AgentDefinition
            from hive.workspace import save_global_agent_config

            defn = AgentDefinition(
                name=self._agent_add_data["name"],
                description=self._agent_add_data["description"],
                system_prompt=self._agent_add_data["system_prompt"],
                tools=raw_tools,
                max_steps=max_steps,
                scope=scope,
            )
            if scope == "global":
                save_global_agent_config(defn.to_dict())
            else:
                save_agent_config(self._cwd, defn.to_dict())
            self.print(
                f"[#FFC107]Agent '{defn.name}' saved ({scope}).[/#FFC107] "
                f"Run it with: /agent {defn.name} <goal>"
            )
            self._agent_adding = False
            self._agent_add_step = 0
            self._agent_add_data = {}
            event.app.invalidate()

        @kb.add(
            "escape",
            filter=has_focus(self.input_field) & _agent_adding_active,
            eager=True,
        )
        def agent_add_cancel(event):
            self._agent_adding = False
            self._agent_add_step = 0
            self._agent_add_data = {}
            self.input_field.text = ""
            self.print("[dim]Agent creation cancelled.[/dim]")
            event.app.invalidate()

        # -- Inline hint navigation + Tab to accept --
        def _hint_matches() -> list[str]:
            text = self.input_field.text
            if "\n" in text or not text.startswith("/"):
                return []
            parts = text.split(" ", 1)
            first = parts[0]
            # Sub-command hints: "/cmd " or "/cmd sub_prefix"
            if len(parts) == 2 and first in SUB_COMMANDS:
                sub_prefix = parts[1]
                return [
                    s
                    for s in SUB_COMMANDS[first]
                    if s.startswith(sub_prefix) and s != sub_prefix
                ][:5]
            # Only show sub-command hints (not top-level) when command is exact and has subs
            if first in SUB_COMMANDS and text == first:
                return []
            return [c for c in _COMMANDS if c.startswith(text) and c != text][:5]

        def _inline_match() -> str | None:
            """First command matching the last space-separated slash-token, or None."""
            text = self.input_field.text
            if "\n" in text or text.startswith("/"):
                return None
            last = text.rsplit(" ", 1)[-1]
            if len(last) > 1 and last.startswith("/"):
                matches = [c for c in _COMMANDS if c.startswith(last) and c != last]
                return matches[0] if matches else None
            return None

        _has_hints = Condition(lambda: bool(_hint_matches()))
        _has_inline = Condition(lambda: _inline_match() is not None)

        @kb.add(
            "tab",
            filter=has_focus(self.input_field)
            & (_has_hints | _has_inline)
            & _not_modal,
            eager=True,
        )
        @kb.add(
            "enter",
            filter=has_focus(self.input_field) & _has_hints & _not_modal,
            eager=True,
        )
        def tab_complete(event):
            matches = _hint_matches()
            if matches:
                idx = min(self._hint_idx, len(matches) - 1)
                text = self.input_field.text
                parts = text.split(" ", 1)
                if len(parts) == 2 and parts[0] in SUB_COMMANDS:
                    # Sub-command completion: "/cmd sub" → "/cmd add"
                    new_text = parts[0] + " " + matches[idx]
                else:
                    # Top-level completion: "/res" → "/resume"
                    new_text = matches[idx]
            else:
                # Inline slash-command — replace last word only
                completion = _inline_match()
                if not completion:
                    return
                text = self.input_field.text
                prefix = text.rsplit(" ", 1)[0]
                new_text = prefix + " " + completion
            self.input_field.text = new_text
            self.input_field.buffer.cursor_position = len(new_text)
            self._hint_idx = 0
            event.app.invalidate()

        @kb.add(
            "up",
            filter=has_focus(self.input_field) & _has_hints & _not_picker,
            eager=True,
        )
        def hints_up(event):
            matches = _hint_matches()
            self._hint_idx = (min(self._hint_idx, len(matches) - 1) - 1) % len(matches)
            event.app.invalidate()

        @kb.add(
            "down",
            filter=has_focus(self.input_field) & _has_hints & _not_picker,
            eager=True,
        )
        def hints_down(event):
            matches = _hint_matches()
            self._hint_idx = (min(self._hint_idx, len(matches) - 1) + 1) % len(matches)
            event.app.invalidate()

        # -- History navigation (only when hints are not showing) --
        @kb.add(
            "up",
            filter=has_focus(self.input_field) & _not_picker & ~_has_hints,
            eager=True,
        )
        def history_up(event):
            buf = event.current_buffer
            if buf.document.cursor_position_row > 0:
                buf.cursor_up()
            elif buf.document.cursor_position_col > 0:
                buf.cursor_position = buf.document.get_start_of_line_position()
            else:
                new_text = self._history.navigate_back(self.input_field.text)
                if new_text is not None:
                    self.input_field.text = new_text

        @kb.add(
            "down",
            filter=has_focus(self.input_field) & _not_picker & ~_has_hints,
            eager=True,
        )
        def history_down(event):
            buf = event.current_buffer
            if buf.document.cursor_position_row < buf.document.line_count - 1:
                buf.cursor_down()
            elif buf.document.cursor_position_col < len(buf.document.current_line):
                buf.cursor_position += buf.document.get_end_of_line_position()
            else:
                new_text = self._history.navigate_forward()
                if new_text is not None:
                    self.input_field.text = new_text
                    self.input_field.buffer.cursor_position = len(new_text)

        # -- Right arrow accepts inline ghost suggestion when cursor is at end --
        _suggestion_visible = Condition(
            lambda: bool(
                self.input_field.buffer.suggestion
                and self.input_field.buffer.document.is_cursor_at_the_end
            )
        )

        @kb.add(
            "right",
            filter=has_focus(self.input_field) & _suggestion_visible & _not_modal,
            eager=True,
        )
        def accept_suggestion(event):
            s = event.current_buffer.suggestion
            if s:
                event.current_buffer.insert_text(s.text)

        @kb.add("c-j", filter=has_focus(self.input_field), eager=True)
        def newline(event):
            event.current_buffer.newline()

        @kb.add("c-c")
        def ctrl_c(event):
            if self._agent_abort is not None and not self._agent_abort.is_set():
                self._agent_abort.set()
                self.print("[dim]Aborting agent…[/dim]")
                return
            if self._ai_abort is not None and not self._ai_abort.is_set():
                self._ai_abort.set()
                self.print("[dim]Aborting…[/dim]")
                return
            now = time.monotonic()
            if now - self._last_ctrl_c < 1.0:
                event.app.exit()
            else:
                self._last_ctrl_c = now
                self._transient_hint = "Press Ctrl+C again to exit"
                event.app.invalidate()

                def _clear_hint():
                    self._transient_hint = ""
                    try:
                        self.app.invalidate()
                    except Exception:
                        pass

                threading.Timer(1.0, _clear_hint).start()

        @kb.add("c-d")
        def exit_app(event):
            event.app.exit()

        # --- scroll handler — patched onto both windows so scroll always goes to output ---
        def _scroll_output(mouse_event: MouseEvent):
            total = len(self._welcome_lines) + len(self._output_lines)
            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                self._scroll_offset = min(total, self._scroll_offset + 3)
                self.app.invalidate()
                return None
            elif mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                self._scroll_offset = max(0, self._scroll_offset - 3)
                self.app.invalidate()
                return None
            return NotImplemented

        # --- output window ---
        # _ScrollableWindow routes scroll events to _scroll_output via a
        # subclass override rather than instance monkey-patching.
        self.output_window = _ScrollableWindow(
            content=FormattedTextControl(self._get_fragments, focusable=False),
            wrap_lines=False,
            on_scroll=_scroll_output,
        )
        # TextArea.window is a plain Window with no public scroll hook.
        # We patch the instance attribute as a best-effort fallback so that
        # scroll also works when the cursor is in the input field.
        try:
            self.input_field.window._mouse_handler = _scroll_output
        except Exception:
            logger.warning("Could not attach scroll handler to input window.")

        # --- suggestions + transient-hint window (rendered below the input frame) ---
        # Always at least 1 row tall so the layout never shifts when a hint appears.
        def _hints_fragments():
            parts: list = []
            matches = _hint_matches()
            if matches:
                idx = min(self._hint_idx, len(matches) - 1)
                text = self.input_field.text
                input_parts = text.split(" ", 1)
                is_sub = len(input_parts) == 2 and input_parts[0] in SUB_COMMANDS
                cmd_prefix = (input_parts[0] + " ") if is_sub else ""
                style_selected = "class:slash-sub" if is_sub else "class:slash-cmd"
                for i, cmd in enumerate(matches):
                    label = cmd_prefix + cmd
                    if i == idx:
                        parts += [(style_selected, f" ▶ {label}"), ("", "\n")]
                    else:
                        parts += [("class:hint", f"   {label}"), ("", "\n")]
            if self._transient_hint:
                parts += [("class:transient-hint", f"  {self._transient_hint}")]
            return parts

        def _hints_height() -> int:
            return len(_hint_matches()) + 1  # +1: reserved row for transient hint

        hints_window = Window(
            content=FormattedTextControl(_hints_fragments),
            height=_hints_height,
            dont_extend_height=True,
        )

        @kb.add("pageup")
        def scroll_up(event):
            total = len(self._welcome_lines) + len(self._output_lines)
            self._scroll_offset = min(total, self._scroll_offset + 3)

        @kb.add("pagedown")
        def scroll_down(event):
            self._scroll_offset = max(0, self._scroll_offset - 3)

        # --- layout ---
        layout = Layout(
            HSplit([self.output_window, Frame(self.input_field), hints_window]),
            focused_element=self.input_field,
        )

        self.app = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=True,
            style=_STYLE,
            output=_output,
            mouse_support=True,
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _current_width(self) -> int:
        try:
            from prompt_toolkit import get_app

            return get_app().output.get_size().columns
        except Exception:
            return shutil.get_terminal_size().columns

    def _output_height(self) -> int:
        try:
            from prompt_toolkit import get_app

            rows = get_app().output.get_size().rows
        except Exception:
            rows = shutil.get_terminal_size().lines
        col = self._current_width()
        available_cols = max(1, col - 4)
        text = self.input_field.text or ""
        input_lines = text.split("\n") if text else [""]
        input_h = max(
            1,
            sum(
                max(1, (len(line) + available_cols - 1) // available_cols)
                for line in input_lines
            ),
        )
        # hints_window is always at least 1 row (reserved for transient hint)
        # plus one row per matching slash-command completion.
        cmd_text = text.strip()
        if cmd_text.startswith("/") and "\n" not in cmd_text:
            n_hints = len(
                [c for c in _COMMANDS if c.startswith(cmd_text) and c != cmd_text][:5]
            )
        else:
            n_hints = 0
        hints_h = n_hints + 1
        return max(1, rows - input_h - 2 - hints_h)

    def _render_to_lines(self, renderable, width: int | None = None) -> list[str]:
        buf = io.StringIO()
        if width is None:
            width = self._current_width()
        console = Console(
            file=buf, force_terminal=True, highlight=False, width=max(1, width - 1)
        )
        console.print(renderable)
        return buf.getvalue().splitlines()

    def _get_fragments(self) -> list:
        """Return the prompt_toolkit fragments for the current visible slice."""
        width = self._current_width()

        def _slice(lines: list[str]) -> list:
            available = self._output_height()
            total = len(lines)
            if total == 0:
                return []
            start = max(0, total - available)
            return list(to_formatted_text(ANSI("\n".join(lines[start:]))))

        if self._awaiting_name:
            if width != self._name_panel_width:
                self._name_panel_width = width
                self._welcome_lines = self._render_to_lines(
                    build_name_panel(self._name_is_rename), width
                )
            return _slice(self._welcome_lines)

        if self._awaiting_trust:
            trust_key = (width, self._trust_choice)
            if trust_key != self._trust_panel_key:
                self._trust_panel_key = trust_key
                self._welcome_lines = self._render_to_lines(
                    build_trust_panel(self._cwd, width, self._trust_choice, self._lang),
                    width,
                )
            return _slice(self._welcome_lines)

        if self._picking_language:
            lang_key = (width, self._lang_idx)
            if lang_key != self._lang_panel_key:
                self._lang_panel_key = lang_key
                self._welcome_lines = self._render_to_lines(
                    build_language_panel(LANG_OPTIONS, self._lang_idx, width), width
                )
            return _slice(self._welcome_lines)

        if self._resuming:
            resume_key = (
                width,
                self._resume_idx,
            )
            if resume_key != self._resume_panel_key:
                self._resume_panel_key = resume_key
                self._welcome_lines = self._render_to_lines(
                    build_resume_panel(
                        self._resume_sessions,
                        self._resume_idx,
                        width,
                        self._lang,
                    ),
                    width,
                )
            return _slice(self._welcome_lines)

        if self._picking_model:
            model_key = (width, self._model_idx)
            if model_key != self._model_panel_key:
                self._model_panel_key = model_key
                self._welcome_lines = self._render_to_lines(
                    build_model_panel(
                        self._model_list, self._model, self._model_idx, self._lang
                    ),
                    width,
                )
            return _slice(self._welcome_lines)

        if self._managing_mcp:
            mcp_key = (
                width,
                self._mcp_idx,
                self._mcp_confirm_delete,
                frozenset(self._mcp_reconnecting),
                frozenset(self._mcp.servers().keys()),
            )
            if mcp_key != self._mcp_panel_key:
                self._mcp_panel_key = mcp_key
                self._welcome_lines = self._render_to_lines(
                    build_mcp_panel(
                        self._mcp_configs,
                        set(self._mcp.servers().keys()),
                        self._mcp_reconnecting,
                        self._mcp_idx,
                        self._mcp_confirm_delete,
                        self._lang,
                    ),
                    width,
                )
            return _slice(self._welcome_lines)

        mcp_names = sorted(self._mcp.servers().keys())
        welcome_key = (width, tuple(mcp_names))
        if welcome_key != (self._welcome_width, self._welcome_mcp_key):
            self._welcome_width = width
            self._welcome_mcp_key = tuple(mcp_names)
            session_id = self._session.id if self._session else None
            self._welcome_lines = self._render_to_lines(
                build_welcome(
                    width,
                    self._cwd,
                    session_id,
                    self._user_name,
                    self._lang,
                    mcp_servers=mcp_names if mcp_names else None,
                ),
                width,
            )

        available = self._output_height()
        # Pad welcome to always fill the viewport so the first output line
        # replaces the last empty line instead of jumping the welcome down.
        welcome_padded = self._welcome_lines + [
            "" for _ in range(max(0, available - len(self._welcome_lines)))
        ]
        all_lines = welcome_padded + self._output_lines
        total = len(all_lines)
        if total == 0:
            return []
        end = min(total, max(available, total - self._scroll_offset))
        start = max(0, end - available)
        return list(to_formatted_text(ANSI("\n".join(all_lines[start:end]))))

    def _split_conversation(self) -> "tuple[str | None, list[dict]]":
        """Return (summary_text_or_None, recent_pairs)."""
        if self._conversation and self._conversation[0].get("role") == "system":
            content = self._conversation[0].get("content", "")
            if content.startswith(SUMMARY_PREFIX):
                return content, self._conversation[1:]
        return None, self._conversation

    def _maybe_summarize(self) -> None:
        """Trigger background rolling summarization if token threshold exceeded."""
        current_summary, recent_pairs = self._split_conversation()
        if not self._summarizer.needs_summarization(recent_pairs):
            return

        def on_done(new_conv: list[dict]) -> None:
            self._conversation = new_conv
            if self._session:
                save_conversation(self._session, self._conversation)

        self._summarizer.try_summarize_background(
            current_summary, recent_pairs, on_done
        )

    def _save_session_sync(self) -> None:
        """Save all session state. Runs a final synchronous summarization if needed."""
        import time as _time

        deadline = _time.monotonic() + 10
        while self._summarizer.is_busy and _time.monotonic() < deadline:
            _time.sleep(0.05)

        # Final sync summarization if there are unsummarized pairs + existing summary
        current_summary, recent_pairs = self._split_conversation()
        if recent_pairs and current_summary is not None:
            try:
                text = self._summarizer.summarize_sync(current_summary, recent_pairs)
                self._conversation = [
                    {
                        "role": "system",
                        "content": f"{SUMMARY_PREFIX}{text}",
                    }
                ]
            except Exception:
                pass

        last_user = next(
            (
                m["content"]
                for m in reversed(self._full_conversation)
                if m.get("role") == "user"
            ),
            "",
        )
        last_message = last_user[:60] + ("\u2026" if len(last_user) > 60 else "")
        ended_at = datetime.now().isoformat()

        with ThreadPoolExecutor(max_workers=4) as ex:
            ex.submit(save_output, self._session, self._output_lines)
            ex.submit(save_conversation, self._session, self._conversation)
            ex.submit(save_full_conversation, self._session, self._full_conversation)
            ex.submit(update_meta, self._session, ended_at, last_message)

    def _load_session_inline(self, session: Session) -> None:
        if self._session is not None:
            s = self._session
            out = self._output_lines[:]
            conv = self._conversation[:]
            full = self._full_conversation[:]
            last_user = next(
                (m["content"] for m in reversed(full) if m.get("role") == "user"), ""
            )
            last_message = last_user[:60] + ("\u2026" if len(last_user) > 60 else "")
            ended_at = datetime.now().isoformat()
            with ThreadPoolExecutor(max_workers=4) as ex:
                ex.submit(save_output, s, out)
                ex.submit(save_conversation, s, conv)
                ex.submit(save_full_conversation, s, full)
                ex.submit(update_meta, s, ended_at, last_message)

        self._session = session
        self._conversation = load_conversation(session)
        self._full_conversation = load_full_conversation(session)
        if not self._full_conversation and self._conversation:
            self._full_conversation = [
                m for m in self._conversation if m.get("role") != "system"
            ]
        self._output_lines = load_output(session)
        self._history.path = session.history_path
        self._scroll_offset = 0
        if self.app.is_running:
            self.app.invalidate()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def print(self, renderable):
        """Render a rich renderable into the output area and jump to the bottom."""
        new_lines = self._render_to_lines(renderable)
        self._output_lines.extend(new_lines)
        self._scroll_offset = 0
        if self.app.is_running:
            self.app.invalidate()

    def handle_input(self, text: str):
        if text == "/exit":
            self.app.exit()
            return

        if text == "/name":
            self._name_is_rename = True
            self._name_panel_width = -1
            self._awaiting_name = True
            if self.app.is_running:
                self.app.invalidate()
            return

        if text == "/language":
            self._lang_idx = next(
                (i for i, (code, _) in enumerate(LANG_OPTIONS) if code == self._lang),
                0,
            )
            self._lang_panel_key = (-1, -1)
            self._picking_language = True
            if self.app.is_running:
                self.app.invalidate()
            return

        if text == "/resume":
            sessions = list_sessions(self._cwd)
            if not sessions:
                self.print(t("sessions.none_resume", self._lang))
                return
            self._resume_sessions = sessions
            self._resume_idx = 0
            self._resume_panel_key = (-1, -1)
            self._resuming = True
            if self.app.is_running:
                self.app.invalidate()
            return

        if text == "/sessions":
            sessions = list_sessions(self._cwd)
            if not sessions:
                self.print(t("sessions.none", self._lang))
                return
            table = Table(title=t("sessions.title", self._lang), border_style="#FFC107")
            table.add_column(t("sessions.col.id", self._lang), style="#FFC107")
            table.add_column(t("sessions.col.started", self._lang))
            table.add_column(t("sessions.col.ended", self._lang))
            table.add_column(t("sessions.col.commands", self._lang), justify="right")
            table.add_column(t("sessions.col.last_message", self._lang))
            for s in sessions:
                cmd_count = 0
                if s.history_path.exists():
                    lines = [
                        ln
                        for ln in s.history_path.read_text(
                            encoding="utf-8"
                        ).splitlines()
                        if ln.strip()
                    ]
                    cmd_count = len(lines)
                table.add_row(
                    s.id,
                    s.started,
                    (s.meta.get("ended_at") or "")[:16],
                    str(cmd_count),
                    s.meta.get("last_message", ""),
                )
            self.print(table)
            return

        if text == "/mcp" or text.startswith("/mcp "):
            parts = text.split(None, 1)
            sub = parts[1].strip() if len(parts) > 1 else ""
            if sub == "manage":
                _merged: dict[str, MCPServerConfig] = {}
                for d in get_global_mcp_configs():
                    cfg = MCPServerConfig.from_dict(d)
                    cfg.scope = "global"
                    _merged[cfg.name] = cfg
                for d in get_local_mcp_configs(self._cwd):
                    cfg = MCPServerConfig.from_dict(d)
                    cfg.scope = "local"
                    _merged[cfg.name] = cfg
                self._mcp_configs = list(_merged.values())
                self._mcp_idx = 0
                self._mcp_panel_key = (-1, -1)
                self._mcp_confirm_delete = None
                self._managing_mcp = True
                self._welcome_width = -1
                if self.app.is_running:
                    self.app.invalidate()
                return
            # Default: show table of connected servers
            servers = self._mcp.servers()
            if not servers:
                self.print(t("mcp.none", self._lang))
                return
            table = Table(title=t("mcp.title", self._lang), border_style="#FFC107")
            table.add_column(t("mcp.col.server", self._lang), style="#FFC107")
            table.add_column(t("mcp.col.tools", self._lang), justify="right")
            for name, conn in servers.items():
                table.add_row(name, str(len(conn.tools)))
            self.print(table)
            return

        if text == "/use" or text.startswith("/use "):
            # Split into at most 3 parts: "/use", <server>, <optional query>
            parts = text.split(None, 2)
            sub = parts[1].strip() if len(parts) > 1 else ""
            query = parts[2].strip() if len(parts) > 2 else ""
            connected = set(self._mcp.servers().keys())
            if not sub:
                if self._active_mcp_servers:
                    self.print(
                        t("use.active", self._lang).format(
                            servers=", ".join(sorted(self._active_mcp_servers))
                        )
                    )
                else:
                    self.print(t("use.none_active", self._lang))
                if connected:
                    self.print(
                        t("use.available", self._lang).format(
                            servers=", ".join(sorted(connected))
                        )
                    )
                return
            if sub == "all":
                self._active_mcp_servers = set(connected)
                self.print(t("use.activated_all", self._lang))
                return
            if sub == "none":
                self._active_mcp_servers.clear()
                self.print(t("use.deactivated_all", self._lang))
                return
            if sub not in connected:
                self.print(t("use.not_connected", self._lang).format(name=sub))
                return
            if query:
                # Activate the server (if not already) and immediately route
                # the query to the AI — e.g. "/use engra search for X"
                if sub not in self._active_mcp_servers:
                    self._active_mcp_servers.add(sub)
                    self.print(t("use.activated", self._lang).format(name=sub))
                self._start_ai_response(query)
                return
            if sub in self._active_mcp_servers:
                self._active_mcp_servers.discard(sub)
                self.print(t("use.deactivated", self._lang).format(name=sub))
            else:
                self._active_mcp_servers.add(sub)
                self.print(t("use.activated", self._lang).format(name=sub))
            return

        if text.startswith("/model"):
            parts = text.split(None, 1)
            if len(parts) == 1:
                # No argument — open the interactive model picker.
                models = (
                    self._provider.list_models()
                    if hasattr(self._provider, "list_models")
                    else []
                )
                if not models:
                    self.print(t("model.picker_none", self._lang))
                    return
                self._model_list = models
                # Pre-select the current model if present, otherwise start at top.
                try:
                    self._model_idx = models.index(self._model)
                except ValueError:
                    self._model_idx = 0
                self._model_panel_key = (-1, -1)
                self._picking_model = True
                self._welcome_width = -1
                self.app.invalidate()
            else:
                new_model = parts[1].strip()
                if not new_model:
                    self.print(t("model.usage", self._lang))
                else:
                    self._model = new_model
                    if self._session:
                        set_model(self._cwd, new_model)
                    self.print(t("model.set", self._lang).format(model=new_model))
            return

        if text == "/agent" or text.startswith("/agent "):
            parts = text.split(None, 2)
            sub = parts[1].strip() if len(parts) > 1 else ""
            if not sub or sub == "list":
                self._cmd_agent_list()
                return
            if sub == "add":
                self._agent_adding = True
                self._agent_add_step = 0
                self._agent_add_data = {}
                self.input_field.text = ""
                self.print(_AGENT_ADD_PROMPTS[0])
                if self.app.is_running:
                    self.app.invalidate()
                return
            if sub == "delete":
                name = parts[2].strip() if len(parts) > 2 else ""
                self._cmd_agent_delete(name)
                return
            if sub == "edit":
                name = parts[2].strip() if len(parts) > 2 else ""
                self._cmd_agent_edit(name)
                return
            if sub == "copy":
                rest = parts[2].strip() if len(parts) > 2 else ""
                copy_parts = rest.split(None, 1)
                copy_name = copy_parts[0] if copy_parts else ""
                copy_target = copy_parts[1].strip() if len(copy_parts) > 1 else ""
                self._cmd_agent_copy(copy_name, copy_target)
                return
            goal = parts[2].strip() if len(parts) > 2 else ""
            if not goal:
                self.print(
                    f"[yellow]Usage:[/yellow] /agent {sub} <goal>\n"
                    "Provide a goal for the agent to accomplish."
                )
                return
            self._start_agent(sub, goal)
            return

        self._start_ai_response(text)

    def _cmd_agent_list(self) -> None:
        from hive.agent import load_agent_definitions

        definitions = load_agent_definitions(self._cwd)
        if not definitions:
            self.print("No agents available.")
            return
        table = Table(title="Agents", border_style="#FFC107")
        table.add_column("Name", style="#FFC107")
        table.add_column("Description")
        table.add_column("Tools")
        table.add_column("Max Steps", justify="right")
        table.add_column("Scope", justify="center")
        for defn in definitions.values():
            tools_str = ", ".join(defn.tools) if defn.tools is not None else "all"
            scope_label = {"local": "L", "global": "G", "builtin": "B"}.get(
                defn.scope, defn.scope
            )
            table.add_row(
                defn.name, defn.description, tools_str, str(defn.max_steps), scope_label
            )
        self.print(table)

    def _cmd_agent_delete(self, name: str) -> None:
        from hive.agent import load_agent_definitions
        from hive.workspace import delete_agent_config, delete_global_agent_config

        if not name:
            self.print("[yellow]Usage:[/yellow] /agent delete <name>")
            return
        definitions = load_agent_definitions(self._cwd)
        defn = definitions.get(name)
        if defn is None:
            self.print(
                f"[red]Unknown agent '{name}'.[/red] "
                "Use '/agent list' to see available agents."
            )
            return
        if defn.scope == "builtin":
            self.print(
                f"[red]Cannot delete built-in agent '{name}'.[/red] "
                "Built-in agents are part of Hive."
            )
            return
        if defn.scope == "global":
            delete_global_agent_config(name)
        else:
            delete_agent_config(self._cwd, name)
        self.print(f"[#FFC107]Agent '{name}' deleted.[/#FFC107]")

    def _cmd_agent_edit(self, name: str) -> None:
        import os
        import platform
        import subprocess

        from hive.agent import load_agent_definitions
        from hive.workspace import get_global_agents_dir

        if not name:
            self.print("[yellow]Usage:[/yellow] /agent edit <name>")
            return
        definitions = load_agent_definitions(self._cwd)
        defn = definitions.get(name)
        if defn is None:
            self.print(
                f"[red]Unknown agent '{name}'.[/red] "
                "Use '/agent list' to see available agents."
            )
            return
        if defn.scope == "builtin":
            self.print(
                f"[yellow]'{name}' is a built-in agent.[/yellow] "
                f"To customise it, use /agent add to recreate it with your changes."
            )
            return
        if defn.scope == "global":
            agent_path = get_global_agents_dir() / f"{name}.md"
        else:
            agent_path = self._cwd / ".hive" / "agents" / f"{name}.md"
        if not agent_path.exists():
            self.print(f"[red]Agent file not found: {agent_path}[/red]")
            return
        editor = (
            os.environ.get("EDITOR")
            or os.environ.get("VISUAL")
            or ("notepad" if platform.system() == "Windows" else "nano")
        )
        try:
            subprocess.Popen([editor, str(agent_path)])
            self.print(
                f"[#FFC107]Opened '{name}' in {editor}.[/#FFC107] "
                "Restart Hive to apply changes."
            )
        except Exception as exc:
            self.print(
                f"[red]Could not open editor ({exc}).[/red]\n"
                f"Edit manually: {agent_path}"
            )

    def _cmd_agent_copy(self, name: str, target: str) -> None:
        from hive.agent import load_agent_definitions
        from hive.workspace import save_agent_config, save_global_agent_config

        if not name or target not in ("local", "global"):
            self.print("[yellow]Usage:[/yellow] /agent copy <name> local|global")
            return
        definitions = load_agent_definitions(self._cwd)
        defn = definitions.get(name)
        if defn is None:
            self.print(
                f"[red]Unknown agent '{name}'.[/red] "
                "Use '/agent list' to see available agents."
            )
            return
        if target == "global":
            save_global_agent_config(defn.to_dict())
        else:
            save_agent_config(self._cwd, defn.to_dict())
        self.print(f"[#FFC107]Agent '{name}' copied to {target} scope.[/#FFC107]")

    def _start_agent(self, agent_name: str, goal: str) -> None:
        from hive.agent import AgentRunner, AgentStep, load_agent_definitions

        definitions = load_agent_definitions(self._cwd)
        defn = definitions.get(agent_name)
        if defn is None:
            self.print(
                f"[red]Unknown agent '{agent_name}'.[/red] "
                "Use '/agent list' to see available agents."
            )
            return

        self.print(f"[#FFC107]▶ Agent: {defn.name}[/#FFC107]  {goal}")

        abort_event = threading.Event()
        self._agent_abort = abort_event
        self._ai_thinking = True

        width = self._current_width()

        # Auto-activate any MCP servers required by the agent's tool whitelist.
        # Derives server names from prefixed tool names (e.g. "gitmcp__stage_all" → "gitmcp").
        if defn.tools:
            required_servers = {t.split("__")[0] for t in defn.tools if "__" in t}
            auto_activated = required_servers - self._active_mcp_servers
            self._active_mcp_servers |= auto_activated
        else:
            auto_activated = set()

        mcp_tools = [
            tool
            for tool in self._mcp.list_tools()
            if tool["function"]["name"].split("__")[0] in self._active_mcp_servers
        ]
        all_tools = AI_TOOLS + mcp_tools

        def _tool_executor(name: str, args: dict) -> str:
            if "__" in name:
                return self._mcp.call_tool(name, args)
            return run_tool(name, args, cwd=self._cwd)

        _tool_start: dict[tuple, float] = {}
        _agent_start = time.monotonic()

        def _on_step(step: AgentStep) -> None:
            step_tag = f"[dim][{step.step_num}/{defn.max_steps}][/dim] "
            if step.tool_name and not step.tool_result:
                # Tool call starting — record start time
                _tool_start[(step.step_num, step.tool_name)] = time.monotonic()
                args_preview = " ".join(str(v) for v in step.tool_args.values())[:60]
                lines = self._render_to_lines(
                    f"  {step_tag}[dim]↳ {step.tool_name}[/dim]"
                    + (f"  {args_preview}" if args_preview else ""),
                    width=width,
                )
                self._output_lines.extend(lines)
            elif step.tool_name and step.tool_result:
                # Tool result — show elapsed time
                elapsed = time.monotonic() - _tool_start.get(
                    (step.step_num, step.tool_name), time.monotonic()
                )
                elapsed_str = f"{elapsed:.1f}s"
                preview = step.tool_result[:250].replace("\n", " ")
                lines = self._render_to_lines(
                    f"  [dim]  → {preview}  [{elapsed_str}][/dim]", width=width
                )
                self._output_lines.extend(lines)
            elif step.text:
                # Intermediate or final text
                lines = self._render_to_lines(step.text, width=width)
                self._output_lines.extend(lines)
            self._scroll_offset = 0
            if self.app.is_running:
                self.app.invalidate()

        import platform as _platform
        import subprocess as _sp

        _git_branch = ""
        try:
            _r = _sp.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=self._cwd,
                timeout=5,
            )
            _git_branch = _r.stdout.strip()
        except Exception:
            pass
        enriched_goal = (
            f"[Context: OS={_platform.system()} {_platform.release()}, "
            f"CWD={self._cwd}"
            + (f", git branch={_git_branch}" if _git_branch else "")
            + f"]\n{goal}"
        )

        def _agent_thread() -> None:
            runner = AgentRunner(self._provider, self._model)
            result = runner.run(
                defn, enriched_goal, _tool_executor, _on_step, all_tools, abort_event
            )
            total = time.monotonic() - _agent_start
            total_str = f"{total:.1f}s"

            if result.success:
                self.print(f"[dim]Agent done in {total_str}[/dim]")
            elif not abort_event.is_set():
                self.print(f"[dim]Agent stopped: {result.summary}  [{total_str}][/dim]")

            self._conversation.append({"role": "assistant", "content": result.summary})
            self._full_conversation.append(
                {"role": "assistant", "content": result.summary}
            )
            self._maybe_summarize()

            self._ai_thinking = False
            self._agent_abort = None

            # Deactivate servers that were auto-activated for this agent run.
            if auto_activated:
                self._active_mcp_servers -= auto_activated

            if self.app.is_running:
                self.app.invalidate()

        threading.Thread(target=_agent_thread, daemon=True).start()

    def _start_ai_response(self, user_text: str) -> None:
        """Echo user input, then call the AI in a background thread with a live timer."""
        self.print(f"[#FFC107]→[/#FFC107] {user_text}")
        self._conversation.append({"role": "user", "content": user_text})
        self._full_conversation.append({"role": "user", "content": user_text})
        self._ai_thinking = True

        # Reserve a line in the output for the thinking animation
        thinking_idx = len(self._output_lines)
        self._output_lines.append("")

        start = time.monotonic()
        done = threading.Event()
        abort_event = threading.Event()
        self._ai_abort = abort_event
        result: list[str | None] = [None]
        error: list[str | None] = [None]
        aborted: list[bool] = [False]
        tools_unsupported_flag: list[bool] = [False]
        width = self._current_width()

        mcp_tools = [
            tool
            for tool in self._mcp.list_tools()
            if tool["function"]["name"].split("__")[0] in self._active_mcp_servers
        ]
        all_tools = AI_TOOLS + mcp_tools

        def _tool_executor(name: str, args: dict) -> str:
            if "__" in name:
                return self._mcp.call_tool(name, args)
            return run_tool(name, args, cwd=self._cwd)

        import platform as _platform

        system_content = (
            SYSTEM_PROMPT
            + f"\n\nCurrent working directory: {self._cwd}"
            + f"\nOperating system: {_platform.system()} {_platform.release()}"
        )
        manifest = self._mcp.compact_manifest()
        if manifest:
            system_content += f"\n\n{manifest}"
        if self._active_mcp_servers:
            system_content += (
                "\nActive MCP servers (full schemas included): "
                + ", ".join(sorted(self._active_mcp_servers))
            )

        def _ai_thread() -> None:
            try:
                reply, tools_unsupported = self._provider.chat(
                    [{"role": "system", "content": system_content}]
                    + self._conversation,
                    self._model,
                    tools=all_tools,
                    tool_executor=_tool_executor,
                    abort=abort_event,
                )
                result[0] = reply
                tools_unsupported_flag[0] = tools_unsupported
            except ai._Aborted:
                aborted[0] = True
            except Exception as exc:
                error[0] = str(exc)
            finally:
                self._ai_abort = None
                done.set()

        def _anim_thread() -> None:
            import random

            msg = random.choice(ai.THINKING_MSGS)
            while not done.wait(timeout=1.0):
                elapsed = int(time.monotonic() - start)
                rendered = self._render_to_lines(
                    f"  [dim]{msg}... ({elapsed}s)[/dim]", width=width
                )
                self._output_lines[thinking_idx] = rendered[0] if rendered else ""
                if self.app.is_running:
                    self.app.invalidate()

            elapsed = int(time.monotonic() - start)
            self._ai_thinking = False

            if aborted[0]:
                self._output_lines[thinking_idx] = ""
            elif error[0]:
                self._output_lines[thinking_idx] = t("ai.error", self._lang).format(
                    error=error[0]
                )
            else:
                reply = result[0] or ""
                self._conversation.append({"role": "assistant", "content": reply})
                self._full_conversation.append({"role": "assistant", "content": reply})
                self._maybe_summarize()
                reply_lines = self._render_to_lines(reply, width=width)
                self._output_lines[thinking_idx : thinking_idx + 1] = reply_lines
                if (
                    tools_unsupported_flag[0]
                    and mcp_tools
                    and not self._mcp_tools_unsupported_shown
                ):
                    self._mcp_tools_unsupported_shown = True
                    self._output_lines.extend(
                        self._render_to_lines(
                            f"[dim]{t('mcp.tools_unsupported', self._lang)}[/dim]"
                        )
                    )

            self._scroll_offset = 0
            if self.app.is_running:
                self.app.invalidate()

        threading.Thread(target=_ai_thread, daemon=True).start()
        threading.Thread(target=_anim_thread, daemon=True).start()

    def _save_mcp_configs_all(self) -> None:
        """Persist self._mcp_configs back to the correct scope files."""
        global_cfgs = [c.to_dict() for c in self._mcp_configs if c.scope == "global"]
        local_cfgs = [c.to_dict() for c in self._mcp_configs if c.scope == "local"]
        save_global_mcp_configs(global_cfgs)
        save_mcp_configs(self._cwd, local_cfgs)

    def _connect_mcp_server(self, config: MCPServerConfig) -> None:
        """Connect to one MCP server in a background thread; print on error."""
        try:
            self._mcp.connect(config)
            logger.info("MCP: connected to '%s'", config.name)
        except Exception as exc:
            self.print(t("mcp.error", self._lang).format(name=config.name, error=exc))
        finally:
            self._mcp_panel_key = (-1, -1)
            if self.app.is_running:
                self.app.invalidate()

    def _startup_checks(self) -> None:
        """Run health checks in a background thread and print warnings."""
        import os
        import time as _time

        # Small delay so the welcome panel is visible before warnings appear.
        _time.sleep(1.0)

        if (
            hasattr(self._provider, "is_reachable")
            and not self._provider.is_reachable()
        ):
            url = getattr(self._provider, "base_url", "remote API")
            self.print(t("startup.ollama_unreachable", self._lang).format(url=url))

        # One-time gitscribe warning when ANTHROPIC_API_KEY is missing.
        if "gitscribe_api_key" not in get_warned_flags() and not os.environ.get(
            "ANTHROPIC_API_KEY"
        ):
            for raw in get_mcp_configs(self._cwd):
                cfg = MCPServerConfig.from_dict(raw)
                if cfg.enabled and "gitscribe" in cfg.name.lower():
                    self.print(t("startup.gitscribe_no_key", self._lang))
                    set_warned_flag("gitscribe_api_key")
                    break

    def run(self):
        logger.debug("HiveApp started")
        # Connect to enabled MCP servers in background threads so startup is
        # non-blocking. Errors are printed to the output area once the app runs.
        for raw in get_mcp_configs(self._cwd):
            config = MCPServerConfig.from_dict(raw)
            if config.enabled:
                threading.Thread(
                    target=self._connect_mcp_server,
                    args=(config,),
                    daemon=True,
                ).start()
        threading.Thread(target=self._startup_checks, daemon=True).start()
        try:
            self.app.run()
        finally:
            self._mcp.shutdown()
            if self._session:
                self._save_session_sync()
                print(t("exit.resume", self._lang).format(id=self._session.id))
