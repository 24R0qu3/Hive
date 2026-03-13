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
from prompt_toolkit.input.vt100_parser import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console
from rich.table import Table

from hive import ai
from hive.commands import COMMAND_NAMES, SYSTEM_PROMPT
from hive.i18n import LANG_OPTIONS, t
from hive.log import add_session_handler
from hive.summarizer import SUMMARY_PREFIX, RollingSummarizer
from hive.ui.history import HistoryManager
from hive.ui.panels import (
    build_language_panel,
    build_name_panel,
    build_resume_panel,
    build_trust_panel,
    build_welcome,
)
from hive.user import get_user_name, has_user_name, set_user_name
from hive.workspace import (
    DEFAULT_SUMMARIZATION_TOKEN_LIMIT,
    Session,
    create_workspace,
    get_language,
    get_model,
    get_summarization_token_limit,
    has_language,
    list_sessions,
    load_conversation,
    load_full_conversation,
    load_output,
    new_session,
    save_conversation,
    save_full_conversation,
    save_output,
    set_language,
    set_model,
    update_meta,
)

logger = logging.getLogger(__name__)

# Windows Terminal (kitty keyboard protocol): Shift+Enter → \x1b[13;2u.
# Map it to c-j so we can bind newline to that key.
ANSI_SEQUENCES.setdefault("\x1b[13;2u", Keys.ControlJ)

_STYLE = Style.from_dict(
    {
        "slash-cmd": "#FFC107 bold",
        "hint": "#666666",
    }
)


class _SlashLexer(Lexer):
    """Highlights slash-command tokens anywhere in the input."""

    def lex_document(self, document):
        lines = document.lines

        def get_line(lineno):
            line = lines[lineno]
            parts = line.split(" ")
            fragments: list = []
            for i, part in enumerate(parts):
                if i > 0:
                    fragments.append(("", " "))
                if part.startswith("/") and any(
                    cmd.startswith(part) for cmd in _COMMANDS
                ):
                    fragments.append(("class:slash-cmd", part))
                else:
                    fragments.append(("", part))
            return fragments

        return get_line


# Bare command names from the registry — used for autocomplete and coloring.
_COMMANDS = COMMAND_NAMES


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

        # --- hint state ---
        self._hint_idx: int = 0

        # --- AI state ---
        self._provider: ai.AIProvider = ai.OllamaProvider()
        self._model: str = get_model(cwd) or ai.DEFAULT_MODEL
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

        # --- output state ---
        self._welcome_lines: list[str] = []
        self._welcome_width: int = -1
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
            # Match against the last space-separated token if it's a slash prefix
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
            )
        )
        # Blocks history nav (but not name — user is typing freely there)
        _not_picker = ~Condition(
            lambda: self._resuming or self._picking_language or self._awaiting_name
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
        def resume_cancel(event):
            self._resuming = False
            self._welcome_width = -1
            event.app.invalidate()

        # -- Inline hint navigation + Tab to accept --
        def _hint_matches() -> list[str]:
            text = self.input_field.text
            if "\n" in text or not text.startswith("/"):
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
                # Whole input is a slash-command prefix — replace entirely
                idx = min(self._hint_idx, len(matches) - 1)
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
            now = time.monotonic()
            if now - self._last_ctrl_c < 0.5:
                event.app.exit()
            else:
                self._last_ctrl_c = now

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
        self.output_window = Window(
            content=FormattedTextControl(self._get_fragments, focusable=False),
            wrap_lines=False,
        )
        self.output_window._mouse_handler = _scroll_output
        self.input_field.window._mouse_handler = _scroll_output

        # --- suggestions window (rendered below the input frame) ---
        def _hints_fragments():
            matches = _hint_matches()
            if not matches:
                return []
            idx = min(self._hint_idx, len(matches) - 1)
            parts: list = []
            for i, cmd in enumerate(matches):
                if i == idx:
                    parts += [("class:slash-cmd", f" ▶ {cmd}"), ("", "\n")]
                else:
                    parts += [("class:hint", f"   {cmd}"), ("", "\n")]
            return parts

        hints_window = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(_hints_fragments),
                height=lambda: len(_hint_matches()),
                dont_extend_height=True,
            ),
            filter=_has_hints,
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
        return max(1, rows - input_h - 2)

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

        if width != self._welcome_width:
            self._welcome_width = width
            session_id = self._session.id if self._session else None
            self._welcome_lines = self._render_to_lines(
                build_welcome(
                    width, self._cwd, session_id, self._user_name, self._lang
                ),
                width,
            )

        available = self._output_height()
        all_lines = self._welcome_lines + self._output_lines
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

        if text.startswith("/model"):
            parts = text.split(None, 1)
            if len(parts) == 1:
                self.print(t("model.current", self._lang).format(model=self._model))
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

        self._start_ai_response(text)

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
        result: list[str | None] = [None]
        error: list[str | None] = [None]
        width = self._current_width()

        def _ai_thread() -> None:
            try:
                result[0] = self._provider.chat(
                    [{"role": "system", "content": SYSTEM_PROMPT}] + self._conversation,
                    self._model,
                )
            except Exception as exc:
                error[0] = str(exc)
            finally:
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

            if error[0]:
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

            self._scroll_offset = 0
            if self.app.is_running:
                self.app.invalidate()

        threading.Thread(target=_ai_thread, daemon=True).start()
        threading.Thread(target=_anim_thread, daemon=True).start()

    def run(self):
        logger.debug("HiveApp started")
        try:
            self.app.run()
        finally:
            if self._session:
                self._save_session_sync()
                print(t("exit.resume", self._lang).format(id=self._session.id))
