import io
import json
import logging
import shutil
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hive import __version__
from hive.i18n import LANG_OPTIONS, t
from hive.log import add_session_handler
from hive.user import get_user_name, has_user_name, set_user_name
from hive.workspace import (
    Session,
    create_workspace,
    get_language,
    has_language,
    list_sessions,
    load_output,
    new_session,
    save_output,
    set_language,
)

logger = logging.getLogger(__name__)

_WIDE_THRESHOLD = 80

_STYLE = Style.from_dict({"slash-cmd": "#FFC107 bold"})


class _SlashLexer(Lexer):
    """Highlights the slash-command word on the first line of the input."""

    def lex_document(self, document):
        lines = document.lines

        def get_line(lineno):
            line = lines[lineno]
            if lineno == 0 and line.startswith("/"):
                space = line.find(" ")
                if space == -1:
                    return [("class:slash-cmd", line)]
                return [("class:slash-cmd", line[:space]), ("", line[space:])]
            return [("", line)]

        return get_line


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------


def _load_history(path: Path) -> list[str]:
    """Load command history from a JSON-lines file.

    Also migrates the legacy prompt_toolkit FileHistory format
    (lines prefixed with '+', timestamps prefixed with '#').
    """
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            if line.startswith("+"):
                entries.append(line[1:])
    return entries


# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------


def _build_name_panel(is_rename: bool = False) -> Panel:
    """Name prompt panel — always in English, shown before language selection."""
    heading = "What's your new name?" if is_rename else "Welcome to Hive!"
    prompt = "Type your name below and press Enter."
    content = Group(
        Text(""),
        Text(heading, style="bold #FFC107", justify="center"),
        Text(""),
        Text(prompt, style="dim", justify="center"),
        Text(""),
    )
    return Panel(
        content,
        title=f"[bold #FFC107]v{__version__}[/bold #FFC107]",
        title_align="left",
        border_style="#FFC107",
    )


def _build_welcome(
    width: int = 0,
    cwd: Path | None = None,
    session_id: str | None = None,
    name: str | None = None,
    lang: str = "en",
) -> Panel:
    """Build the welcome panel, showing the honeycomb only on wide terminals."""
    logo = Text.assemble(
        ("██╗  ██╗██╗██╗   ██╗███████╗\n", "bold #FFB300"),
        ("██║  ██║██║██║   ██║██╔════╝\n", "bold #FFB300"),
        ("███████║██║╚██╗ ██╔╝█████╗  \n", "bold #FFC107"),
        ("██╔══██║██║ ╚████╔╝ ██╔══╝  \n", "bold #FFC107"),
        ("██║  ██║██║  ╚██╔╝  ███████╗\n", "bold #FFD54F"),
        ("╚═╝  ╚═╝╚═╝   ╚═╝   ╚══════╝", "bold #FFD54F"),
    )

    inner_width = max(1, width - 4)

    if cwd is not None and session_id is not None:
        session_tag = f"#{session_id}"
        cwd_str = str(cwd)
        max_cwd_len = inner_width - len(session_tag) - 2
        if len(cwd_str) > max_cwd_len and max_cwd_len > 3:
            cwd_str = "…" + cwd_str[-(max_cwd_len - 1) :]
        gap = max(1, inner_width - len(cwd_str) - len(session_tag))
        info_line = Text.assemble(
            (cwd_str, "dim"),
            (" " * gap, ""),
            (session_tag, "dim #FFC107"),
        )
        hints: object = Group(
            info_line,
            Text(t("welcome.hint", lang), style="dim", justify="left"),
        )
    elif cwd is not None:
        cwd_str = str(cwd)
        if len(cwd_str) > inner_width - 1 and inner_width > 3:
            cwd_str = "…" + cwd_str[-(inner_width - 2) :]
        hints = Group(
            Text(cwd_str, style="dim"),
            Text(t("welcome.hint", lang), style="dim", justify="left"),
        )
    else:
        hints = Text(t("welcome.hint", lang), style="dim", justify="left")

    greeting = (
        Text(
            t("welcome.greeting", lang).format(name=name),
            style="bold #FFC107",
            justify="center",
        )
        if name
        else None
    )

    if width >= _WIDE_THRESHOLD:
        right = Text.assemble(
            ("   ⬡ ⬡ ⬡\n", "bold #BF360C"),
            ("  ⬡ ⬡ ⬡ ⬡\n", "bold #E65100"),
            (" ⬡ ⬡ ⬡ ⬡ ⬡", "bold #FF8F00"),
            (" ⬡ ⬡ ⬡\n", "bold #BF360C"),
            ("  ⬡ ⬡ ⬡ ⬡", "bold #FFC107"),
            (" ⬡ ⬡ ⬡ ⬡\n", "bold #FF8F00"),
            ("   ⬡ ⬡ ⬡", "bold #E65100"),
            (" ⬡ ⬡ ⬡ ⬡ ⬡\n", "bold #FFD54F"),
            ("  ⬡ ⬡ ⬡ ⬡", "bold #FFC107"),
            (" ⬡ ⬡ ⬡ ⬡\n", "bold #FFC107"),
            (" ⬡ ⬡ ⬡ ⬡ ⬡", "bold #FF8F00"),
            (" ⬡ ⬡ ⬡\n", "bold #BF360C"),
            ("  ⬡ ⬡ ⬡ ⬡\n", "bold #E65100"),
            ("   ⬡ ⬡ ⬡", "bold #BF360C"),
        )
        grid = Table.grid(padding=(0, 3))
        grid.add_column(vertical="middle")
        grid.add_column(vertical="middle")
        grid.add_row(logo, right)
        body = Group(Text(""), grid, Text(""), hints)
        content = Group(greeting, Text(""), body) if greeting else Group(Text(""), body)
    else:
        body = Group(Text(""), logo, Text(""), hints)
        content = Group(greeting, Text(""), body) if greeting else Group(Text(""), body)

    return Panel(
        content,
        title=f"[bold #FFC107]v{__version__}[/bold #FFC107]",
        title_align="left",
        border_style="#FFC107",
    )


def _build_trust_panel(
    cwd: Path, width: int = 0, choice: int = 0, lang: str = "en"
) -> Panel:
    """Trust prompt panel with arrow-key selectable Yes / No."""
    yes_style = "bold #FFC107" if choice == 0 else "dim"
    no_style = "bold #FFC107" if choice == 1 else "dim"

    options = Text.assemble(
        ("▶ " if choice == 0 else "  ", yes_style),
        ("[ Yes ]", yes_style),
        ("    ", ""),
        ("▶ " if choice == 1 else "  ", no_style),
        ("[ No  ]", no_style),
        justify="center",
    )

    content = Group(
        Text(""),
        Text(t("trust.heading", lang), justify="center"),
        Text(""),
        Text(str(cwd), style="bold", justify="center"),
        Text(""),
        Text(t("trust.body1", lang), justify="center"),
        Text(t("trust.body2", lang), justify="center"),
        Text(""),
        options,
        Text(""),
        Text(t("trust.hint", lang), style="dim", justify="center"),
        Text(""),
    )
    return Panel(
        content,
        title=f"[bold #FFC107]v{__version__}[/bold #FFC107]",
        title_align="left",
        border_style="#FFC107",
    )


def _build_language_panel(lang_options: list, idx: int, width: int = 0) -> Panel:
    """Language picker panel — heading and hints update to match the highlighted language."""
    current_lang = lang_options[idx][0]

    rows = []
    for i, (code, label) in enumerate(lang_options):
        selected = i == idx
        prefix = "▶ " if selected else "  "
        style = "bold #FFC107" if selected else ""
        rows.append(Text(f"{prefix}{label}", style=style, justify="center"))

    content = Group(
        Text(""),
        Text(t("lang.heading", current_lang), justify="center"),
        Text(""),
        *rows,
        Text(""),
        Text(t("lang.hint", current_lang), style="dim", justify="center"),
        Text(t("lang.change_later", current_lang), style="dim", justify="center"),
        Text(""),
    )
    return Panel(
        content,
        title=f"[bold #FFC107]v{__version__}[/bold #FFC107]",
        title_align="left",
        border_style="#FFC107",
    )


def _build_resume_panel(
    sessions: list[Session], idx: int, width: int = 0, lang: str = "en"
) -> Panel:
    """Session resume picker panel."""
    rows = []
    for i, s in enumerate(sessions):
        selected = i == idx
        prefix = "▶ " if selected else "  "
        style = "bold #FFC107" if selected else ""
        rows.append(Text(f"{prefix}{s.id}  {s.started}", style=style))

    content = Group(
        Text(""),
        Text(t("resume.heading", lang), justify="center"),
        Text(""),
        *rows,
        Text(""),
        Text(t("resume.hint", lang), style="dim", justify="center"),
        Text(""),
    )
    return Panel(
        content,
        title=f"[bold #FFC107]v{__version__}[/bold #FFC107]",
        title_align="left",
        border_style="#FFC107",
    )


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class HiveApp:
    def __init__(
        self,
        cwd: Path,
        session: Session | None = None,
        trusted: bool = False,
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

        # --- output state ---
        self._welcome_lines: list[str] = []
        self._welcome_width: int = -1
        self._output_lines: list[str] = []
        self._scroll_offset: int = 0

        if session is not None and session.output_path.exists():
            self._output_lines = load_output(session)

        # --- history ---
        if self._session is not None:
            self._history_path: Path | None = self._session.history_path
            self._history: list[str] = _load_history(self._history_path)
        else:
            self._history_path = None
            self._history = []
        self._history_idx: int = len(self._history)
        self._history_draft: str = ""

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
                # Existing workspace without language (or rename mid-session without lang)
                self._picking_language = True
                self._lang_idx = 0
                self._lang_panel_key = (-1, -1)
            else:
                self._welcome_width = -1
            event.app.invalidate()

        # -- Regular submit --
        @kb.add("enter", filter=has_focus(self.input_field) & _not_modal, eager=True)
        def submit(event):
            text = self.input_field.text.strip()
            if text:
                self._history.append(text)
                self._history_idx = len(self._history)
                self._history_draft = ""
                if self._history_path is not None:
                    self._history_path.write_text(
                        "\n".join(json.dumps(e) for e in self._history),
                        encoding="utf-8",
                    )
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
                self._history_path = self._session.history_path
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

        # -- Resume picker: ↑ ↓ to navigate, Enter to confirm, Esc to cancel --
        @kb.add("up", filter=_resume_active, eager=True)
        def resume_up(event):
            self._resume_idx = max(0, self._resume_idx - 1)
            self._resume_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("down", filter=_resume_active, eager=True)
        def resume_down(event):
            self._resume_idx = min(len(self._resume_sessions) - 1, self._resume_idx + 1)
            self._resume_panel_key = (-1, -1)
            event.app.invalidate()

        @kb.add("enter", filter=_resume_active, eager=True)
        def resume_confirm(event):
            self._load_session_inline(self._resume_sessions[self._resume_idx])
            self._resuming = False
            self._welcome_width = -1
            event.app.invalidate()

        @kb.add("escape", filter=_resume_active, eager=True)
        def resume_cancel(event):
            self._resuming = False
            self._welcome_width = -1
            event.app.invalidate()

        # -- History navigation (guarded against all pickers and name prompt) --
        @kb.add("up", filter=has_focus(self.input_field) & _not_picker, eager=True)
        def history_up(event):
            buf = event.current_buffer
            if buf.document.cursor_position_row > 0:
                buf.cursor_up()
            elif buf.document.cursor_position_col > 0:
                buf.cursor_position = buf.document.get_start_of_line_position()
            else:
                if not self._history:
                    return
                if self._history_idx == len(self._history):
                    self._history_draft = self.input_field.text
                if self._history_idx > 0:
                    self._history_idx -= 1
                    self.input_field.text = self._history[self._history_idx]

        @kb.add("down", filter=has_focus(self.input_field) & _not_picker, eager=True)
        def history_down(event):
            buf = event.current_buffer
            if buf.document.cursor_position_row < buf.document.line_count - 1:
                buf.cursor_down()
            elif buf.document.cursor_position_col < len(buf.document.current_line):
                buf.cursor_position += buf.document.get_end_of_line_position()
            else:
                if self._history_idx < len(self._history) - 1:
                    self._history_idx += 1
                    self.input_field.text = self._history[self._history_idx]
                    self.input_field.buffer.cursor_position = len(self.input_field.text)
                elif self._history_idx == len(self._history) - 1:
                    self._history_idx = len(self._history)
                    self.input_field.text = self._history_draft
                    self.input_field.buffer.cursor_position = len(self.input_field.text)

        @kb.add("c-j", filter=has_focus(self.input_field))
        def newline(event):
            event.current_buffer.newline()

        @kb.add("c-c")
        @kb.add("c-d")
        def exit_app(event):
            event.app.exit()

        # --- output window ---
        self.output_window = Window(
            content=FormattedTextControl(self._get_fragments, focusable=False),
            wrap_lines=False,
        )

        @kb.add("pageup")
        def scroll_up(event):
            total = len(self._welcome_lines) + len(self._output_lines)
            self._scroll_offset = min(total, self._scroll_offset + 5)

        @kb.add("pagedown")
        def scroll_down(event):
            self._scroll_offset = max(0, self._scroll_offset - 5)

        # --- layout ---
        layout = Layout(
            HSplit([self.output_window, Frame(self.input_field)]),
            focused_element=self.input_field,
        )

        self.app = Application(layout=layout, key_bindings=kb, full_screen=True, style=_STYLE)

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
                    _build_name_panel(self._name_is_rename), width
                )
            return _slice(self._welcome_lines)

        if self._awaiting_trust:
            trust_key = (width, self._trust_choice)
            if trust_key != self._trust_panel_key:
                self._trust_panel_key = trust_key
                self._welcome_lines = self._render_to_lines(
                    _build_trust_panel(
                        self._cwd, width, self._trust_choice, self._lang
                    ),
                    width,
                )
            return _slice(self._welcome_lines)

        if self._picking_language:
            lang_key = (width, self._lang_idx)
            if lang_key != self._lang_panel_key:
                self._lang_panel_key = lang_key
                self._welcome_lines = self._render_to_lines(
                    _build_language_panel(LANG_OPTIONS, self._lang_idx, width), width
                )
            return _slice(self._welcome_lines)

        if self._resuming:
            resume_key = (width, self._resume_idx)
            if resume_key != self._resume_panel_key:
                self._resume_panel_key = resume_key
                self._welcome_lines = self._render_to_lines(
                    _build_resume_panel(
                        self._resume_sessions, self._resume_idx, width, self._lang
                    ),
                    width,
                )
            return _slice(self._welcome_lines)

        if width != self._welcome_width:
            self._welcome_width = width
            session_id = self._session.id if self._session else None
            self._welcome_lines = self._render_to_lines(
                _build_welcome(
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

    def _load_session_inline(self, session: Session) -> None:
        """Save the current session and restore output + history from another."""
        if self._session is not None:
            save_output(self._session, self._output_lines)
        self._session = session
        self._output_lines = load_output(session)
        self._history_path = session.history_path
        self._history = _load_history(self._history_path)
        self._history_idx = len(self._history)
        self._history_draft = ""
        self._scroll_offset = 0

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
            table.add_column(t("sessions.col.commands", self._lang), justify="right")
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
                table.add_row(s.id, s.started, str(cmd_count))
            self.print(table)
            return

        self.print(f"[#FFC107]→[/#FFC107] {text}")

    def run(self):
        logger.debug("HiveApp started")
        self.app.run()
        if self._session:
            save_output(self._session, self._output_lines)
            print(t("exit.resume", self._lang).format(id=self._session.id))
