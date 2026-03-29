"""Pure render functions for Hive's TUI panels."""

from __future__ import annotations

from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hive import __version__
from hive.i18n import t
from hive.mcp import MCPServerConfig
from hive.workspace import Session

_WIDE_THRESHOLD = 80


def build_name_panel(is_rename: bool = False) -> Panel:
    """Name prompt panel — always shown in English before language is selected."""
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


def build_welcome(
    width: int = 0,
    cwd: Path | None = None,
    session_id: str | None = None,
    name: str | None = None,
    lang: str = "en",
    mcp_servers: list[str] | None = None,
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

    mcp_line: Text | None = None
    if mcp_servers:
        names = ", ".join(mcp_servers)
        mcp_line = Text(f"⬡ {names}", style="dim #FFC107")

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
        hint_parts: list = [info_line]
        if mcp_line:
            hint_parts.append(mcp_line)
        hint_parts.append(Text(t("welcome.hint", lang), style="dim", justify="left"))
        hints: object = Group(*hint_parts)
    elif cwd is not None:
        cwd_str = str(cwd)
        if len(cwd_str) > inner_width - 1 and inner_width > 3:
            cwd_str = "…" + cwd_str[-(inner_width - 2) :]
        hint_parts = [Text(cwd_str, style="dim")]
        if mcp_line:
            hint_parts.append(mcp_line)
        hint_parts.append(Text(t("welcome.hint", lang), style="dim", justify="left"))
        hints = Group(*hint_parts)
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


def build_trust_panel(
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


def build_language_panel(lang_options: list, idx: int, width: int = 0) -> Panel:
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


def build_model_panel(
    models: list[str], current: str, idx: int, lang: str = "en"
) -> Panel:
    """Model picker panel — lists available Ollama models with the current one marked."""
    rows = []
    for i, name in enumerate(models):
        selected = i == idx
        is_current = name == current
        prefix = "▶ " if selected else "  "
        label = f"{name}  [dim]✓[/dim]" if is_current else name
        style = "bold #FFC107" if selected else ("dim" if not is_current else "")
        rows.append(Text.from_markup(f"{prefix}{label}", style=style))

    content = Group(
        Text(""),
        Text(t("model.picker_heading", lang), justify="center"),
        Text(""),
        *rows,
        Text(""),
        Text(t("model.picker_hint", lang), style="dim", justify="center"),
        Text(""),
    )
    return Panel(
        content,
        title=f"[bold #FFC107]v{__version__}[/bold #FFC107]",
        title_align="left",
        border_style="#FFC107",
    )


def build_resume_panel(
    sessions: list[Session],
    idx: int,
    width: int = 0,
    lang: str = "en",
) -> Panel:
    """Session resume picker panel."""
    rows = []
    for i, s in enumerate(sessions):
        selected = i == idx
        prefix = "▶ " if selected else "  "
        style = "bold #FFC107" if selected else ""
        ended = (s.meta.get("ended_at") or "")[:16]
        last_msg = s.meta.get("last_message") or ""
        suffix = f"  {ended}  {last_msg}" if ended or last_msg else ""
        label = f"{prefix}{s.id}  {s.started[:16]}{suffix}"
        rows.append(Text(label, style=style))

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


def build_mcp_panel(
    configs: list[MCPServerConfig],
    connected_names: set[str],
    reconnecting_names: set[str],
    idx: int,
    confirm_delete_name: str | None = None,
    lang: str = "en",
) -> Panel:
    """Interactive MCP server management panel.

    Shows all configured servers with their live connection status.
    The selected row is highlighted; confirm_delete_name shows a warning line.
    """
    rows = []
    for i, config in enumerate(configs):
        selected = i == idx
        prefix = "▶ " if selected else "  "
        style = "bold #FFC107" if selected else ""

        name_part = config.name
        enabled_part = "" if config.enabled else "  [dim][disabled][/dim]"

        if config.name in reconnecting_names:
            status = t("mcp.manage.status.reconnecting", lang)
            status_style = "dim #FFC107"
        elif config.name in connected_names:
            status = t("mcp.manage.status.connected", lang)
            status_style = "bold green"
        else:
            status = t("mcp.manage.status.disconnected", lang)
            status_style = "dim red"

        row = Text.assemble(
            (prefix, style),
            (name_part, style),
            (enabled_part, ""),
            ("  ", ""),
            (status, status_style),
        )
        rows.append(row)

    content_parts: list = [
        Text(""),
        Text(t("mcp.manage.heading", lang), justify="center"),
        Text(""),
        *rows,
        Text(""),
    ]

    if confirm_delete_name is not None:
        content_parts.append(
            Text(
                t("mcp.manage.confirm_delete", lang).format(name=confirm_delete_name),
                style="dim red",
                justify="center",
            )
        )
        content_parts.append(Text(""))

    content_parts.append(
        Text(t("mcp.manage.hint", lang), style="dim", justify="center")
    )
    content_parts.append(Text(""))

    content = Group(*content_parts)
    return Panel(
        content,
        border_style="#FFC107",
        title=f"[bold #FFC107]v{__version__}[/bold #FFC107]",
    )
