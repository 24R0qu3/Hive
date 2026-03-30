"""Tests for hive.user global name storage."""

import json

import pytest

import hive.user as user_mod


@pytest.fixture()
def user_dir(tmp_path, monkeypatch):
    """Redirect hive.user to a temporary config directory."""
    config_dir = tmp_path / "hive-config"
    monkeypatch.setattr(user_mod, "_get_config_dir", lambda: config_dir)
    return config_dir


# ---------------------------------------------------------------------------
# get_user_name
# ---------------------------------------------------------------------------


def test_get_user_name_returns_none_when_no_file(user_dir):
    assert user_mod.get_user_name() is None


def test_get_user_name_returns_stored_name(user_dir):
    user_dir.mkdir(parents=True)
    (user_dir / "user.json").write_text(json.dumps({"name": "Alice"}), encoding="utf-8")
    assert user_mod.get_user_name() == "Alice"


def test_get_user_name_ignores_other_keys(user_dir):
    user_dir.mkdir(parents=True)
    (user_dir / "user.json").write_text(
        json.dumps({"name": "Bob", "other": "stuff"}), encoding="utf-8"
    )
    assert user_mod.get_user_name() == "Bob"


def test_get_user_name_returns_none_when_key_missing(user_dir):
    user_dir.mkdir(parents=True)
    (user_dir / "user.json").write_text(
        json.dumps({"other": "value"}), encoding="utf-8"
    )
    assert user_mod.get_user_name() is None


# ---------------------------------------------------------------------------
# has_user_name
# ---------------------------------------------------------------------------


def test_has_user_name_false_when_no_file(user_dir):
    assert user_mod.has_user_name() is False


def test_has_user_name_true_when_name_set(user_dir):
    user_dir.mkdir(parents=True)
    (user_dir / "user.json").write_text(json.dumps({"name": "Carol"}), encoding="utf-8")
    assert user_mod.has_user_name() is True


def test_has_user_name_false_when_key_missing(user_dir):
    user_dir.mkdir(parents=True)
    (user_dir / "user.json").write_text(
        json.dumps({"other": "value"}), encoding="utf-8"
    )
    assert user_mod.has_user_name() is False


# ---------------------------------------------------------------------------
# set_user_name
# ---------------------------------------------------------------------------


def test_set_user_name_creates_file(user_dir):
    user_mod.set_user_name("Dave")
    assert (user_dir / "user.json").exists()


def test_set_user_name_creates_parent_dirs(user_dir):
    # user_dir doesn't exist yet
    assert not user_dir.exists()
    user_mod.set_user_name("Eve")
    assert user_dir.is_dir()


def test_set_user_name_persists_name(user_dir):
    user_mod.set_user_name("Frank")
    assert user_mod.get_user_name() == "Frank"


def test_set_user_name_overwrites_existing(user_dir):
    user_mod.set_user_name("Grace")
    user_mod.set_user_name("Heidi")
    assert user_mod.get_user_name() == "Heidi"


def test_set_user_name_preserves_other_keys(user_dir):
    user_dir.mkdir(parents=True)
    (user_dir / "user.json").write_text(
        json.dumps({"other": "keep_me"}), encoding="utf-8"
    )
    user_mod.set_user_name("Ivan")
    raw = json.loads((user_dir / "user.json").read_text(encoding="utf-8"))
    assert raw["other"] == "keep_me"
    assert raw["name"] == "Ivan"


def test_set_user_name_writes_valid_json(user_dir):
    user_mod.set_user_name("Judy")
    raw = (user_dir / "user.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict)


def test_has_user_name_true_after_set(user_dir):
    user_mod.set_user_name("Karl")
    assert user_mod.has_user_name() is True


# ---------------------------------------------------------------------------
# get_warned_flags / set_warned_flag
# ---------------------------------------------------------------------------


def test_get_warned_flags_empty_when_no_file(user_dir):
    assert user_mod.get_warned_flags() == set()


def test_set_warned_flag_creates_entry(user_dir):
    user_mod.set_warned_flag("some_key")
    assert "some_key" in user_mod.get_warned_flags()


def test_set_warned_flag_multiple_keys(user_dir):
    user_mod.set_warned_flag("key_a")
    user_mod.set_warned_flag("key_b")
    flags = user_mod.get_warned_flags()
    assert "key_a" in flags
    assert "key_b" in flags


def test_set_warned_flag_idempotent(user_dir):
    user_mod.set_warned_flag("x")
    user_mod.set_warned_flag("x")
    assert list(user_mod.get_warned_flags()).count("x") == 1


def test_set_warned_flag_preserves_user_name(user_dir):
    user_mod.set_user_name("Lena")
    user_mod.set_warned_flag("foo")
    assert user_mod.get_user_name() == "Lena"
