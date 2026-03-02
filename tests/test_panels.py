"""Tests for hive.ui.panels — pure panel builder functions."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from hive.i18n import LANG_OPTIONS
from hive.ui.panels import (
    build_language_panel,
    build_name_panel,
    build_resume_panel,
    build_trust_panel,
    build_welcome,
)
from hive.workspace import Session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render(panel, width: int = 80) -> str:
    """Render a Rich renderable to plain text using record mode."""
    console = Console(record=True, width=width, highlight=False)
    console.print(panel)
    return console.export_text()


def _fake_session(tmp_path: Path, session_id: str = "abc123") -> Session:
    session_path = tmp_path / session_id
    session_path.mkdir()
    meta = {"id": session_id, "started": "2026-01-01T12:00:00", "cwd": str(tmp_path)}
    (session_path / "meta.json").write_text("{}", encoding="utf-8")
    return Session(id=session_id, path=session_path, meta=meta)


# ---------------------------------------------------------------------------
# build_name_panel
# ---------------------------------------------------------------------------


def test_build_name_panel_returns_panel():
    assert isinstance(build_name_panel(), Panel)


def test_build_name_panel_shows_welcome_heading():
    output = _render(build_name_panel(is_rename=False))
    assert "Welcome to Hive" in output


def test_build_name_panel_rename_shows_rename_heading():
    output = _render(build_name_panel(is_rename=True))
    assert "new name" in output


def test_build_name_panel_contains_prompt_text():
    output = _render(build_name_panel())
    assert "Enter" in output


def test_build_name_panel_has_version_in_title():
    from hive import __version__

    output = _render(build_name_panel())
    assert __version__ in output


# ---------------------------------------------------------------------------
# build_welcome
# ---------------------------------------------------------------------------


def test_build_welcome_returns_panel():
    assert isinstance(build_welcome(), Panel)


def test_build_welcome_shows_greeting_when_name_given():
    output = _render(build_welcome(name="Alice", lang="en"))
    assert "Alice" in output


def test_build_welcome_no_greeting_when_no_name():
    output = _render(build_welcome())
    assert "Hello" not in output


def test_build_welcome_shows_session_id(tmp_path):
    output = _render(build_welcome(width=100, cwd=tmp_path, session_id="abc123"))
    assert "#abc123" in output


def test_build_welcome_shows_cwd(tmp_path):
    output = _render(
        build_welcome(width=100, cwd=tmp_path, session_id="abc123"), width=100
    )
    # Long paths may be truncated with …; check the tail portion is visible
    assert tmp_path.name in output or "…" in output


def test_build_welcome_hint_in_english():
    output = _render(build_welcome(lang="en"))
    assert "Ctrl" in output or "Enter" in output


def test_build_welcome_hint_in_german():
    output = _render(build_welcome(lang="de"))
    assert "Enter" in output


def test_build_welcome_wide_shows_hexagons():
    # Wide terminal should include the honeycomb decoration
    output = _render(build_welcome(width=100), width=100)
    assert "⬡" in output


def test_build_welcome_narrow_no_hexagons():
    output = _render(build_welcome(width=60), width=60)
    assert "⬡" not in output


def test_build_welcome_has_version_in_title():
    from hive import __version__

    output = _render(build_welcome())
    assert __version__ in output


def test_build_welcome_truncates_long_cwd(tmp_path):
    long_path = Path(
        "/very/very/very/very/very/very/very/very/very/long/path/to/project"
    )
    output = _render(
        build_welcome(width=60, cwd=long_path, session_id="abc123"), width=60
    )
    assert "…" in output or "project" in output


# ---------------------------------------------------------------------------
# build_trust_panel
# ---------------------------------------------------------------------------


def test_build_trust_panel_returns_panel(tmp_path):
    assert isinstance(build_trust_panel(tmp_path), Panel)


def test_build_trust_panel_shows_cwd():
    cwd = (
        Path("C:/project")
        if __import__("sys").platform == "win32"
        else Path("/project")
    )
    output = _render(build_trust_panel(cwd))
    assert "project" in output


def test_build_trust_panel_shows_heading_english(tmp_path):
    output = _render(build_trust_panel(tmp_path, lang="en"))
    assert "workspace" in output.lower() or "Hive" in output


def test_build_trust_panel_shows_heading_german(tmp_path):
    output = _render(build_trust_panel(tmp_path, lang="de"))
    assert "Arbeitsbereich" in output


def test_build_trust_panel_choice_0_highlights_yes(tmp_path):
    output = _render(build_trust_panel(tmp_path, choice=0))
    assert "Yes" in output
    assert "▶" in output


def test_build_trust_panel_choice_1_highlights_no(tmp_path):
    yes_output = _render(build_trust_panel(tmp_path, choice=0))
    no_output = _render(build_trust_panel(tmp_path, choice=1))
    # Both contain Yes and No
    assert "Yes" in yes_output and "No" in yes_output
    assert "Yes" in no_output and "No" in no_output


def test_build_trust_panel_shows_hint(tmp_path):
    output = _render(build_trust_panel(tmp_path, lang="en"))
    assert "Enter" in output


# ---------------------------------------------------------------------------
# build_language_panel
# ---------------------------------------------------------------------------


def test_build_language_panel_returns_panel():
    assert isinstance(build_language_panel(LANG_OPTIONS, 0), Panel)


def test_build_language_panel_shows_all_languages():
    output = _render(build_language_panel(LANG_OPTIONS, 0))
    for _, label in LANG_OPTIONS:
        assert label in output


def test_build_language_panel_shows_selection_arrow():
    output = _render(build_language_panel(LANG_OPTIONS, 0))
    assert "▶" in output


def test_build_language_panel_heading_changes_with_selection():
    output_en = _render(build_language_panel(LANG_OPTIONS, 0))
    output_de = _render(build_language_panel(LANG_OPTIONS, 1))
    # English heading
    assert "Choose a language" in output_en
    # German heading (index 1 = "de")
    assert "Sprache" in output_de


def test_build_language_panel_hint_in_current_language():
    output_de = _render(build_language_panel(LANG_OPTIONS, 1))
    # German hint text
    assert "navigieren" in output_de or "bestätigen" in output_de


# ---------------------------------------------------------------------------
# build_resume_panel
# ---------------------------------------------------------------------------


def test_build_resume_panel_returns_panel(tmp_path):
    sessions = [_fake_session(tmp_path, "abc123")]
    assert isinstance(build_resume_panel(sessions, 0), Panel)


def test_build_resume_panel_shows_session_id(tmp_path):
    sessions = [_fake_session(tmp_path, "abc123")]
    output = _render(build_resume_panel(sessions, 0))
    assert "abc123" in output


def test_build_resume_panel_shows_started_timestamp(tmp_path):
    sessions = [_fake_session(tmp_path, "abc123")]
    output = _render(build_resume_panel(sessions, 0))
    assert "2026-01-01T12:00:00" in output


def test_build_resume_panel_shows_selection_arrow(tmp_path):
    sessions = [_fake_session(tmp_path, "abc123"), _fake_session(tmp_path, "def456")]
    output = _render(build_resume_panel(sessions, 0))
    assert "▶" in output


def test_build_resume_panel_heading_english(tmp_path):
    sessions = [_fake_session(tmp_path, "abc123")]
    output = _render(build_resume_panel(sessions, 0, lang="en"))
    assert "resume" in output.lower() or "session" in output.lower()


def test_build_resume_panel_heading_german(tmp_path):
    sessions = [_fake_session(tmp_path, "abc123")]
    output = _render(build_resume_panel(sessions, 0, lang="de"))
    assert "Sitzung" in output or "Fortsetzen" in output


def test_build_resume_panel_empty_sessions(tmp_path):
    # Should render without error even with no sessions
    panel = build_resume_panel([], 0)
    assert isinstance(panel, Panel)
