"""Unit tests for bot.__main__ — the Telegram commands menu builder."""

import pytest

from bot.__main__ import _bot_commands_for


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_bot_commands_menu_contains_all_user_facing_commands(lang: str) -> None:
    """The Telegram slash menu lists every user-facing command for both languages."""
    commands = {c.command for c in _bot_commands_for(lang)}
    assert commands == {
        "start",
        "list",
        "search",
        "reminders",
        "ideas",
        "config",
        "reindex",
        "cancel",
    }


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_bot_commands_menu_descriptions_are_non_empty(lang: str) -> None:
    """Every entry in the slash menu has a non-empty localized description."""
    for command in _bot_commands_for(lang):
        assert command.description, f"Empty description for /{command.command} ({lang})"


def test_bot_commands_menu_descriptions_differ_between_languages() -> None:
    """Russian and English descriptions are genuinely localized — not duplicates."""
    ru = {c.command: c.description for c in _bot_commands_for("ru")}
    en = {c.command: c.description for c in _bot_commands_for("en")}
    # At least the two new commands must differ; we assert on all to catch regressions.
    for command, ru_desc in ru.items():
        assert ru_desc != en[command], f"/{command} description not localized"
