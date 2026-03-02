"""Tests for hive.ui.history — HistoryManager and load_history_file."""

import json

from hive.ui.history import HistoryManager, load_history_file

# ---------------------------------------------------------------------------
# load_history_file
# ---------------------------------------------------------------------------


def test_load_returns_empty_when_file_missing(tmp_path):
    assert load_history_file(tmp_path / "history") == []


def test_load_returns_empty_when_file_is_empty(tmp_path):
    p = tmp_path / "history"
    p.write_text("", encoding="utf-8")
    assert load_history_file(p) == []


def test_load_reads_json_lines(tmp_path):
    p = tmp_path / "history"
    p.write_text(
        "\n".join(json.dumps(e) for e in ["hello", "world"]),
        encoding="utf-8",
    )
    assert load_history_file(p) == ["hello", "world"]


def test_load_multiline_entry(tmp_path):
    p = tmp_path / "history"
    p.write_text(json.dumps("line1\nline2"), encoding="utf-8")
    assert load_history_file(p) == ["line1\nline2"]


def test_load_migrates_old_filehistory_format(tmp_path):
    p = tmp_path / "history"
    p.write_text(
        "# 2026-02-27 23:32:21.239492\n+hello\n# 2026-02-27 23:32:21.239492\n+world\n",
        encoding="utf-8",
    )
    assert load_history_file(p) == ["hello", "world"]


def test_load_skips_timestamp_lines(tmp_path):
    p = tmp_path / "history"
    p.write_text("# 2026-02-27 23:32:21.239492\n", encoding="utf-8")
    assert load_history_file(p) == []


def test_load_skips_blank_lines(tmp_path):
    p = tmp_path / "history"
    p.write_text(
        json.dumps("hello") + "\n\n" + json.dumps("world") + "\n",
        encoding="utf-8",
    )
    assert load_history_file(p) == ["hello", "world"]


def test_load_mixed_old_and_new_format(tmp_path):
    p = tmp_path / "history"
    p.write_text(
        "# 2026-02-27 23:32:21.239492\n+old entry\n" + json.dumps("new entry") + "\n",
        encoding="utf-8",
    )
    assert load_history_file(p) == ["old entry", "new entry"]


# ---------------------------------------------------------------------------
# HistoryManager — construction
# ---------------------------------------------------------------------------


def test_manager_empty_without_path():
    hm = HistoryManager()
    assert hm.entries == []
    assert len(hm) == 0
    assert not hm


def test_manager_loads_on_init(tmp_path):
    p = tmp_path / "history"
    p.write_text(json.dumps("cmd1") + "\n" + json.dumps("cmd2"), encoding="utf-8")
    hm = HistoryManager(p)
    assert hm.entries == ["cmd1", "cmd2"]


def test_manager_none_path_skips_load():
    hm = HistoryManager(path=None)
    assert hm.entries == []


# ---------------------------------------------------------------------------
# HistoryManager — __len__ and __bool__
# ---------------------------------------------------------------------------


def test_manager_bool_false_when_empty():
    hm = HistoryManager()
    assert not hm


def test_manager_bool_true_when_has_entries(tmp_path):
    p = tmp_path / "history"
    p.write_text(json.dumps("x"), encoding="utf-8")
    hm = HistoryManager(p)
    assert hm


def test_manager_len_zero_when_empty():
    assert len(HistoryManager()) == 0


def test_manager_len_matches_entries(tmp_path):
    p = tmp_path / "history"
    p.write_text("\n".join(json.dumps(e) for e in ["a", "b", "c"]), encoding="utf-8")
    hm = HistoryManager(p)
    assert len(hm) == 3


# ---------------------------------------------------------------------------
# HistoryManager — append
# ---------------------------------------------------------------------------


def test_append_adds_entry():
    hm = HistoryManager()
    hm.append("hello")
    assert hm.entries == ["hello"]


def test_append_saves_to_file(tmp_path):
    p = tmp_path / "history"
    hm = HistoryManager(p)
    hm.append("hello")
    assert p.exists()
    assert load_history_file(p) == ["hello"]


def test_append_does_not_save_when_no_path():
    hm = HistoryManager()
    hm.append("hello")  # should not raise
    assert hm.entries == ["hello"]


def test_append_resets_navigation_to_end():
    hm = HistoryManager()
    hm.append("a")
    hm.append("b")
    hm.navigate_back("draft")
    hm.navigate_back("")
    hm.append("c")
    # After append, navigate_forward should return None (already at end)
    assert hm.navigate_forward() is None


# ---------------------------------------------------------------------------
# HistoryManager — navigate_back
# ---------------------------------------------------------------------------


def test_navigate_back_returns_none_when_empty():
    hm = HistoryManager()
    assert hm.navigate_back("current") is None


def test_navigate_back_returns_last_entry():
    hm = HistoryManager()
    hm.append("cmd1")
    hm.append("cmd2")
    assert hm.navigate_back("") == "cmd2"


def test_navigate_back_saves_draft():
    hm = HistoryManager()
    hm.append("cmd1")
    hm.navigate_back("my draft")
    # We're now at cmd1 (the last/only entry); navigate_forward returns the draft
    result = hm.navigate_forward()
    assert result == "my draft"


def test_navigate_back_returns_none_at_first_entry():
    hm = HistoryManager()
    hm.append("only")
    hm.navigate_back("")
    # Already at first entry, another back should return None
    assert hm.navigate_back("") is None


def test_navigate_back_walks_history():
    hm = HistoryManager()
    for cmd in ["a", "b", "c"]:
        hm.append(cmd)
    assert hm.navigate_back("") == "c"
    assert hm.navigate_back("") == "b"
    assert hm.navigate_back("") == "a"
    assert hm.navigate_back("") is None


# ---------------------------------------------------------------------------
# HistoryManager — navigate_forward
# ---------------------------------------------------------------------------


def test_navigate_forward_returns_none_when_empty():
    hm = HistoryManager()
    assert hm.navigate_forward() is None


def test_navigate_forward_returns_none_at_end():
    hm = HistoryManager()
    hm.append("cmd1")
    assert hm.navigate_forward() is None


def test_navigate_forward_returns_next_entry():
    hm = HistoryManager()
    hm.append("cmd1")
    hm.append("cmd2")
    hm.navigate_back("")
    hm.navigate_back("")
    assert hm.navigate_forward() == "cmd2"


def test_navigate_forward_returns_draft_past_last_entry():
    hm = HistoryManager()
    hm.append("cmd1")
    hm.navigate_back("my draft")
    hm.navigate_forward()  # back to end → returns "my draft"
    assert hm.navigate_forward() is None  # already at live position


# ---------------------------------------------------------------------------
# HistoryManager — path setter
# ---------------------------------------------------------------------------


def test_path_setter_reloads_history(tmp_path):
    p1 = tmp_path / "h1"
    p2 = tmp_path / "h2"
    p1.write_text(json.dumps("from-p1"), encoding="utf-8")
    p2.write_text(json.dumps("from-p2"), encoding="utf-8")

    hm = HistoryManager(p1)
    assert hm.entries == ["from-p1"]

    hm.path = p2
    assert hm.entries == ["from-p2"]


def test_path_setter_none_clears_history(tmp_path):
    p = tmp_path / "history"
    p.write_text(json.dumps("cmd"), encoding="utf-8")
    hm = HistoryManager(p)
    hm.path = None
    assert hm.entries == []


def test_path_setter_resets_draft(tmp_path):
    p1 = tmp_path / "h1"
    p2 = tmp_path / "h2"
    p1.write_text(json.dumps("cmd1"), encoding="utf-8")
    p2.write_text(json.dumps("cmd2"), encoding="utf-8")

    hm = HistoryManager(p1)
    hm.navigate_back("saved draft")

    hm.path = p2
    # Draft should be cleared — forward from new history end returns None
    assert hm.navigate_forward() is None


def test_path_getter_returns_current_path(tmp_path):
    p = tmp_path / "history"
    hm = HistoryManager(p)
    assert hm.path == p
