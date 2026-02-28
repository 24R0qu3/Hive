import json

from hive.ui.app import _load_history


def test_returns_empty_when_file_missing(tmp_path):
    assert _load_history(tmp_path / "history") == []


def test_returns_empty_when_file_is_empty(tmp_path):
    p = tmp_path / "history"
    p.write_text("", encoding="utf-8")
    assert _load_history(p) == []


def test_loads_json_lines(tmp_path):
    p = tmp_path / "history"
    p.write_text(
        "\n".join(json.dumps(e) for e in ["hello", "world"]),
        encoding="utf-8",
    )
    assert _load_history(p) == ["hello", "world"]


def test_loads_multiline_entry(tmp_path):
    p = tmp_path / "history"
    p.write_text(json.dumps("line1\nline2"), encoding="utf-8")
    assert _load_history(p) == ["line1\nline2"]


def test_migrates_old_filehistory_format(tmp_path):
    p = tmp_path / "history"
    p.write_text(
        "# 2026-02-27 23:32:21.239492\n+hello\n# 2026-02-27 23:32:21.239492\n+world\n",
        encoding="utf-8",
    )
    assert _load_history(p) == ["hello", "world"]


def test_skips_timestamp_lines(tmp_path):
    p = tmp_path / "history"
    p.write_text("# 2026-02-27 23:32:21.239492\n", encoding="utf-8")
    assert _load_history(p) == []


def test_skips_blank_lines(tmp_path):
    p = tmp_path / "history"
    p.write_text(
        json.dumps("hello") + "\n\n" + json.dumps("world") + "\n",
        encoding="utf-8",
    )
    assert _load_history(p) == ["hello", "world"]


def test_mixed_old_and_new_format(tmp_path):
    p = tmp_path / "history"
    p.write_text(
        "# 2026-02-27 23:32:21.239492\n+old entry\n" + json.dumps("new entry") + "\n",
        encoding="utf-8",
    )
    assert _load_history(p) == ["old entry", "new entry"]
