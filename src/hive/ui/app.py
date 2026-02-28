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
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hive import __version__
from hive.log import add_session_handler
from hive.workspace import (
    Session,
    create_workspace,
    list_sessions,
    load_output,
    new_session,
    save_output,
)

logger = logging.getLogger(__name__)

# Minimum terminal width to show the honeycomb graphic alongside the logo.
_WIDE_THRESHOLD = 80


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
            if line.startswith("+"):  # old FileHistory entry
                entries.append(line[1:])
            # lines starting with '#' are timestamps — skip them
    return entries


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


def _build_welcome(
    width: int = 0,
    cwd: Path | None = None,
    session_id: str | None = None,
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
            Text(
                "Enter · Ctrl+J for newline · Ctrl+C · /exit",
                style="dim",
                justify="left",
            ),
        )
    elif cwd is not None:
        cwd_str = str(cwd)
        if len(cwd_str) > inner_width - 1 and inner_width > 3:
            cwd_str = "…" + cwd_str[-(inner_width - 2) :]
        hints = Group(
            Text(cwd_str, style="dim"),
            Text(
                "Enter · Ctrl+J for newline · Ctrl+C · /exit",
                style="dim",
                justify="left",
            ),
        )
    else:
        hints = Text(
            "Enter · Ctrl+J for newline · Ctrl+C · /exit",
            style="dim",
            justify="left",
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
        content = Group(Text(""), grid, Text(""), hints)
    else:
        content = Group(Text(""), logo, Text(""), hints)

    return Panel(
        content,
        title=f"[bold #FFC107]v{__version__}[/bold #FFC107]",
        title_align="left",
        border_style="#FFC107",
    )


def _build_trust_panel(cwd: Path, width: int = 0, choice: int = 0) -> Panel:
    """Build the trust prompt panel with arrow-key selectable Yes / No."""
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
        Text("Hive wants to create a local workspace in:", justify="center"),
        Text(""),
        Text(str(cwd), style="bold", justify="center"),
        Text(""),
        Text("This will create a .hive folder for session", justify="center"),
        Text("history, logs, and output.", justify="center"),
        Text(""),
        options,
        Text(""),
        Text("← → to choose · Enter to confirm", style="dim", justify="center"),
        Text(""),
    )
    return Panel(
        content,
        title=f"[bold #FFC107]v{__version__}[/bold #FFC107]",
        title_align="left",
        border_style="#FFC107",
    )


def _build_resume_panel(sessions: "list[Session]", idx: int, width: int = 0) -> Panel:
    """Build the inline session picker panel."""
    rows = []
    for i, s in enumerate(sessions):
        selected = i == idx
        prefix = "▶ " if selected else "  "
        style = "bold #FFC107" if selected else ""
        rows.append(Text(f"{prefix}{s.id}  {s.started}", style=style))

    content = Group(
        Text(""),
        Text("Choose a session to resume:", justify="center"),
        Text(""),
        *rows,
        Text(""),
        Text(
            "↑ ↓ to navigate · Enter to resume · Esc to cancel",
            style="dim",
            justify="center",
        ),
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
        self._awaiting_trust = not trusted and session is None

        # Set up or create session immediately when trust already established
        if session is not None:
            self._session: Session | None = session
            add_session_handler(str(session.log_path))
        elif trusted:
            self._session = new_session(cwd)
            add_session_handler(str(self._session.log_path))
        else:
            self._session = None

        # --- output state ---
        self._welcome_lines: list[str] = []
        self._welcome_width: int = -1
        self._output_lines: list[str] = []
        self._scroll_offset: int = 0

        # Restore output if resuming a session
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

        # --- trust dialog state ---
        self._trust_choice: int = 0  # 0 = Yes, 1 = No
        self._trust_panel_key: tuple = (-1, -1)  # (width, choice)

        # --- resume picker state ---
        self._resuming: bool = False
        self._resume_sessions: list[Session] = []
        self._resume_idx: int = 0
        self._resume_panel_key: tuple = (-1, -1)  # (width, idx)

        # --- input field ---
        self.input_field = TextArea(
            prompt="→ ",
            multiline=True,
            wrap_lines=True,
            scrollbar=False,
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

        _not_resuming = ~Condition(lambda: self._resuming)
        _not_modal = ~Condition(lambda: self._awaiting_trust or self._resuming)

        # Submit: guarded against both modal states
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

        # Trust dialog: ← → to choose, Enter to confirm
        _trust_active = Condition(lambda: self._awaiting_trust)

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
                self._awaiting_trust = False
                self._welcome_width = -1
                event.app.invalidate()
            else:
                event.app.exit()

        # Resume picker: ↑ ↓ to navigate, Enter to confirm, Esc to cancel
        _resume_active = Condition(lambda: self._resuming)

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

        # History navigation: only when not in resume picker
        @kb.add("up", filter=has_focus(self.input_field) & _not_resuming, eager=True)
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

        @kb.add("down", filter=has_focus(self.input_field) & _not_resuming, eager=True)
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

        self.app = Application(layout=layout, key_bindings=kb, full_screen=True)

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

        if self._awaiting_trust:
            trust_key = (width, self._trust_choice)
            if trust_key != self._trust_panel_key:
                self._trust_panel_key = trust_key
                self._welcome_lines = self._render_to_lines(
                    _build_trust_panel(self._cwd, width, self._trust_choice), width
                )
            available = self._output_height()
            total = len(self._welcome_lines)
            if total == 0:
                return []
            start = max(0, total - available)
            return list(to_formatted_text(ANSI("\n".join(self._welcome_lines[start:]))))

        if self._resuming:
            resume_key = (width, self._resume_idx)
            if resume_key != self._resume_panel_key:
                self._resume_panel_key = resume_key
                self._welcome_lines = self._render_to_lines(
                    _build_resume_panel(self._resume_sessions, self._resume_idx, width),
                    width,
                )
            available = self._output_height()
            total = len(self._welcome_lines)
            if total == 0:
                return []
            start = max(0, total - available)
            return list(to_formatted_text(ANSI("\n".join(self._welcome_lines[start:]))))

        if width != self._welcome_width:
            self._welcome_width = width
            session_id = self._session.id if self._session else None
            self._welcome_lines = self._render_to_lines(
                _build_welcome(width, self._cwd, session_id), width
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

        if text == "/resume":
            sessions = list_sessions(self._cwd)
            if not sessions:
                self.print("[dim]No sessions to resume.[/dim]")
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
                self.print("[dim]No sessions found.[/dim]")
                return
            table = Table(title="Sessions", border_style="#FFC107")
            table.add_column("ID", style="#FFC107")
            table.add_column("Started")
            table.add_column("Commands", justify="right")
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
            print(f"\nTo resume:  hive --resume {self._session.id}")
