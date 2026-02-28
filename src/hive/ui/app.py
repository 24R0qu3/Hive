import io
import json
import logging
import shutil
from pathlib import Path

from platformdirs import user_data_dir
from prompt_toolkit import Application
from prompt_toolkit.filters import has_focus
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
# Welcome panel
# ---------------------------------------------------------------------------


def _build_welcome(width: int = 0) -> Panel:
    """Build the welcome panel, showing the honeycomb only on wide terminals."""
    logo = Text.assemble(
        ("██╗  ██╗██╗██╗   ██╗███████╗\n", "bold #FFB300"),
        ("██║  ██║██║██║   ██║██╔════╝\n", "bold #FFB300"),
        ("███████║██║╚██╗ ██╔╝█████╗  \n", "bold #FFC107"),
        ("██╔══██║██║ ╚████╔╝ ██╔══╝  \n", "bold #FFC107"),
        ("██║  ██║██║  ╚██╔╝  ███████╗\n", "bold #FFD54F"),
        ("╚═╝  ╚═╝╚═╝   ╚═╝   ╚══════╝", "bold #FFD54F"),
    )

    hints = Text(
        "Enter · Ctrl+J for newline · Ctrl+C · /exit",
        style="dim",
        justify="left",
    )

    if width >= _WIDE_THRESHOLD:
        # Two hexagon shapes with an amber-to-red gradient radiating outward.
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


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class HiveApp:
    def __init__(self):
        # --- output state ---
        # Welcome and output are stored as separate lists of ANSI text lines.
        # _get_fragments slices the visible portion from the bottom so that new
        # content naturally pushes older content (including the welcome) out of view.
        self._welcome_lines: list[str] = []
        self._welcome_width: int = -1  # -1 forces a render on first _get_fragments call
        self._output_lines: list[str] = []
        self._scroll_offset: int = 0  # 0 = pinned to bottom; positive = scrolled up

        # --- history ---
        history_path = Path(user_data_dir("hive", appauthor=False)) / "history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self._history: list[str] = _load_history(history_path)
        self._history_path = history_path
        self._history_idx: int = len(self._history)
        self._history_draft: str = ""  # preserves typed text while navigating history

        # --- input field ---
        # get_line_prefix adds a two-space indent on continuation lines so they
        # align with the text that follows the "→ " prompt.
        self.input_field = TextArea(
            prompt="→ ",
            multiline=True,
            wrap_lines=True,
            scrollbar=False,
            get_line_prefix=lambda lineno, wrap_count: (
                "  " if lineno > 0 or wrap_count > 0 else ""
            ),
        )

        # The input grows one row per visual line (including wrapped lines).
        # Ceiling division: (len + w - 1) // w gives the number of wrapped rows.
        def get_input_height() -> int:
            try:
                from prompt_toolkit import get_app

                col = get_app().output.get_size().columns
            except Exception:
                col = shutil.get_terminal_size().columns
            available = max(1, col - 4)  # col minus frame borders and prompt width
            text = self.input_field.text or ""
            lines = text.split("\n") if text else [""]
            total = sum(
                max(1, (len(line) + available - 1) // available) for line in lines
            )
            return max(1, total)

        self.input_field.window.height = get_input_height

        # --- key bindings ---
        kb = KeyBindings()

        @kb.add("enter", filter=has_focus(self.input_field), eager=True)
        def submit(event):
            text = self.input_field.text.strip()
            if text:
                self._history.append(text)
                self._history_idx = len(self._history)
                self._history_draft = ""
                self._history_path.write_text(
                    "\n".join(json.dumps(e) for e in self._history),
                    encoding="utf-8",
                )
                self.input_field.text = ""
                self.handle_input(text)

        # Up/Down behave like a shell: move the cursor within multi-line input
        # first; only navigate history once the cursor reaches the top/bottom edge.
        @kb.add("up", filter=has_focus(self.input_field), eager=True)
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

        @kb.add("down", filter=has_focus(self.input_field), eager=True)
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
        # FormattedTextControl calls _get_fragments on every render, so the
        # visible slice is always recalculated from the current terminal size.
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
        """Return the current terminal width; falls back to shutil before app starts."""
        try:
            from prompt_toolkit import get_app

            return get_app().output.get_size().columns
        except Exception:
            return shutil.get_terminal_size().columns

    def _output_height(self) -> int:
        """Return the number of rows available for output content.

        Total rows minus the input field height minus the two frame border rows.
        """
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
        """Render any rich renderable to a list of ANSI text lines."""
        buf = io.StringIO()
        if width is None:
            width = self._current_width()
        console = Console(
            file=buf, force_terminal=True, highlight=False, width=max(1, width - 1)
        )
        console.print(renderable)
        return buf.getvalue().splitlines()

    def _get_fragments(self) -> list:
        """Return the prompt_toolkit fragments for the current visible slice.

        Re-renders the welcome panel when the terminal width changes.
        Slices the last N lines from (welcome + output) that fit the output
        area so new content pushes older content — including the welcome — upward.
        """
        width = self._current_width()
        if width != self._welcome_width:
            self._welcome_width = width
            self._welcome_lines = self._render_to_lines(_build_welcome(width), width)

        available = self._output_height()
        all_lines = self._welcome_lines + self._output_lines
        total = len(all_lines)

        if total == 0:
            return []

        # Calculate the visible slice, shifted up by the scroll offset.
        end = min(total, max(available, total - self._scroll_offset))
        start = max(0, end - available)
        visible = all_lines[start:end]

        return list(to_formatted_text(ANSI("\n".join(visible))))

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
        self.print(f"[#FFC107]→[/#FFC107] {text}")

    def run(self):
        logger.debug("HiveApp started")
        self.app.run()
