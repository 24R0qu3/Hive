"""Tests for hive.i18n translation helpers."""

import pytest

from hive.i18n import LANG_OPTIONS, t

# ---------------------------------------------------------------------------
# LANG_OPTIONS
# ---------------------------------------------------------------------------


def test_lang_options_is_list_of_tuples():
    assert isinstance(LANG_OPTIONS, list)
    for item in LANG_OPTIONS:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_lang_options_contains_english():
    codes = [code for code, _ in LANG_OPTIONS]
    assert "en" in codes


def test_lang_options_contains_german():
    codes = [code for code, _ in LANG_OPTIONS]
    assert "de" in codes


def test_lang_options_labels_are_strings():
    for code, label in LANG_OPTIONS:
        assert isinstance(code, str) and isinstance(label, str)


# ---------------------------------------------------------------------------
# t() — basic lookups
# ---------------------------------------------------------------------------


def test_t_returns_english_string():
    result = t("welcome.greeting", "en")
    assert isinstance(result, str)
    assert len(result) > 0


def test_t_returns_german_string():
    result = t("trust.heading", "de")
    assert isinstance(result, str)
    assert len(result) > 0


def test_t_english_and_german_differ_for_trust():
    en = t("trust.heading", "en")
    de = t("trust.heading", "de")
    assert en != de


# ---------------------------------------------------------------------------
# t() — fallback behaviour
# ---------------------------------------------------------------------------


def test_t_falls_back_to_english_for_unknown_lang():
    en = t("welcome.greeting", "en")
    result = t("welcome.greeting", "xx")
    assert result == en


def test_t_falls_back_to_key_for_missing_key():
    result = t("no.such.key.ever", "en")
    assert result == "no.such.key.ever"


def test_t_falls_back_to_key_for_unknown_lang_and_key():
    result = t("totally.missing", "zz")
    assert result == "totally.missing"


def test_t_default_lang_is_english():
    assert t("welcome.greeting") == t("welcome.greeting", "en")


# ---------------------------------------------------------------------------
# t() — greeting format string
# ---------------------------------------------------------------------------


def test_greeting_en_contains_placeholder():
    greeting = t("welcome.greeting", "en")
    assert "{name}" in greeting


def test_greeting_de_contains_placeholder():
    greeting = t("welcome.greeting", "de")
    assert "{name}" in greeting


def test_greeting_en_formats_correctly():
    greeting = t("welcome.greeting", "en").format(name="Alice")
    assert "Alice" in greeting


def test_greeting_de_formats_correctly():
    greeting = t("welcome.greeting", "de").format(name="Alice")
    assert "Alice" in greeting


# ---------------------------------------------------------------------------
# t() — exit.resume format string
# ---------------------------------------------------------------------------


def test_exit_resume_en_contains_id_placeholder():
    s = t("exit.resume", "en")
    assert "{id}" in s


def test_exit_resume_de_contains_id_placeholder():
    s = t("exit.resume", "de")
    assert "{id}" in s


def test_exit_resume_formats_correctly():
    s = t("exit.resume", "en").format(id="a3f9b2")
    assert "a3f9b2" in s


# ---------------------------------------------------------------------------
# t() — coverage of every expected key in English
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "name.heading",
        "name.prompt",
        "name.rename_heading",
        "name.rename_prompt",
        "trust.heading",
        "trust.body1",
        "trust.body2",
        "trust.hint",
        "lang.heading",
        "lang.hint",
        "lang.change_later",
        "welcome.greeting",
        "welcome.hint",
        "resume.heading",
        "resume.hint",
        "sessions.title",
        "sessions.col.id",
        "sessions.col.started",
        "sessions.col.commands",
        "sessions.none",
        "sessions.none_resume",
        "exit.resume",
    ],
)
def test_all_english_keys_resolve_to_non_key(key):
    result = t(key, "en")
    assert result != key, f"Key '{key}' was not found in English strings"
