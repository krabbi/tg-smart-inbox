"""Unit tests for the /config command handler and settings menu."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.handlers import config as config_module
from bot.handlers.config import (
    _CB_CONFIG,
    _SETTINGS,
    _config_menu_keyboard,
    _Setting,
    _settings_by_key,
    cb_config_pick,
    cmd_config,
)


@pytest.fixture
def stub_timezone_launcher() -> Iterator[AsyncMock]:
    """Replace the real timezone FSM launcher inside the settings registry with an AsyncMock."""
    launcher = AsyncMock()
    patched = tuple(
        _Setting(key=s.key, label=s.label, launch=launcher) if s.key == "timezone" else s
        for s in _SETTINGS
    )
    with patch.object(config_module, "_SETTINGS", patched):
        yield launcher


def make_message(user_id: int = 123) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


def make_callback(data: str, user_id: int = 123) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.answer = AsyncMock()
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.message = MagicMock(spec=Message)
    cb.message.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    return cb


def make_state() -> MagicMock:
    state = MagicMock(spec=FSMContext)
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.update_data = AsyncMock()
    return state


# ── Registry / keyboard helpers ──────────────────────────────────────────────


def test_settings_registry_contains_timezone() -> None:
    keys = {s.key for s in _SETTINGS}
    assert "timezone" in keys


def test_settings_by_key_indexes_every_registered_setting() -> None:
    index = _settings_by_key()
    assert len(index) == len(_SETTINGS)
    for s in _SETTINGS:
        assert index[s.key] is s


def test_config_menu_keyboard_has_one_button_per_setting() -> None:
    kb = _config_menu_keyboard()
    all_buttons = [b for row in kb.inline_keyboard for b in row]
    assert len(all_buttons) == len(_SETTINGS)
    labels = {b.text for b in all_buttons}
    assert "🕐 Часовой пояс" in labels


def test_config_menu_keyboard_callback_data_uses_prefix() -> None:
    kb = _config_menu_keyboard()
    for row in kb.inline_keyboard:
        for button in row:
            assert button.callback_data is not None
            assert button.callback_data.startswith(_CB_CONFIG)


# ── /config command ──────────────────────────────────────────────────────────


async def test_cmd_config_without_args_shows_menu() -> None:
    msg = make_message()
    state = make_state()
    cmd = CommandObject(prefix="/", command="config", args=None)

    await cmd_config(msg, cmd, state)

    msg.answer.assert_awaited_once()
    kb = msg.answer.call_args.kwargs["reply_markup"]
    assert kb is not None
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "🕐 Часовой пояс" in labels
    # The menu should not touch FSM state.
    state.set_state.assert_not_awaited()


async def test_cmd_config_with_empty_args_shows_menu() -> None:
    msg = make_message()
    state = make_state()
    cmd = CommandObject(prefix="/", command="config", args="   ")

    await cmd_config(msg, cmd, state)

    msg.answer.assert_awaited_once()
    assert msg.answer.call_args.kwargs.get("reply_markup") is not None


async def test_cmd_config_timezone_launches_fsm(stub_timezone_launcher: AsyncMock) -> None:
    msg = make_message()
    state = make_state()
    cmd = CommandObject(prefix="/", command="config", args="timezone")

    await cmd_config(msg, cmd, state)

    stub_timezone_launcher.assert_awaited_once_with(msg, state)
    msg.answer.assert_not_awaited()


async def test_cmd_config_is_case_insensitive_for_subcommand(
    stub_timezone_launcher: AsyncMock,
) -> None:
    msg = make_message()
    state = make_state()
    cmd = CommandObject(prefix="/", command="config", args="TimeZone")

    await cmd_config(msg, cmd, state)

    stub_timezone_launcher.assert_awaited_once_with(msg, state)


async def test_cmd_config_strips_extra_words_from_args(
    stub_timezone_launcher: AsyncMock,
) -> None:
    # `/config timezone extra garbage` → we still dispatch to `timezone`
    msg = make_message()
    state = make_state()
    cmd = CommandObject(prefix="/", command="config", args="timezone extra garbage")

    await cmd_config(msg, cmd, state)

    stub_timezone_launcher.assert_awaited_once_with(msg, state)


async def test_cmd_config_unknown_setting_replies_with_help() -> None:
    msg = make_message()
    state = make_state()
    cmd = CommandObject(prefix="/", command="config", args="nonexistent")

    await cmd_config(msg, cmd, state)

    msg.answer.assert_awaited_once()
    text = msg.answer.call_args[0][0]
    assert "Неизвестная" in text or "неизвестная" in text.lower()
    # No keyboard for the error message — user should rerun /config to see the menu.
    assert msg.answer.call_args.kwargs.get("reply_markup") is None


# ── Callback (inline button) ─────────────────────────────────────────────────


async def test_cb_config_pick_timezone_launches_fsm(stub_timezone_launcher: AsyncMock) -> None:
    cb = make_callback(f"{_CB_CONFIG}timezone")
    state = make_state()

    await cb_config_pick(cb, state)

    cb.answer.assert_awaited_once()
    stub_timezone_launcher.assert_awaited_once_with(cb.message, state)


async def test_cb_config_pick_unknown_key_is_ignored(stub_timezone_launcher: AsyncMock) -> None:
    cb = make_callback(f"{_CB_CONFIG}nosuch")
    state = make_state()

    await cb_config_pick(cb, state)

    cb.answer.assert_awaited_once()
    stub_timezone_launcher.assert_not_awaited()
    cb.message.answer.assert_not_awaited()
    cb.message.edit_text.assert_not_awaited()


async def test_cb_config_pick_without_message_returns_early(
    stub_timezone_launcher: AsyncMock,
) -> None:
    cb = make_callback(f"{_CB_CONFIG}timezone")
    cb.message = None
    state = make_state()

    await cb_config_pick(cb, state)

    cb.answer.assert_awaited_once()
    stub_timezone_launcher.assert_not_awaited()


async def test_cb_config_pick_without_data_returns_early(
    stub_timezone_launcher: AsyncMock,
) -> None:
    cb = make_callback(f"{_CB_CONFIG}timezone")
    cb.data = None
    state = make_state()

    await cb_config_pick(cb, state)

    cb.answer.assert_awaited_once()
    stub_timezone_launcher.assert_not_awaited()
