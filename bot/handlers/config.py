"""`/config` command: user-facing settings menu and sub-commands.

The command is designed to be extensible: each setting is declared once in
`_SETTINGS` (label, sub-command, FSM launcher). Adding a new setting — e.g.
`/config language` — only requires appending another entry and the FSM entry
point; the menu, router, and dispatch logic stay untouched.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.handlers.timezone_setup import start_timezone_setup

router = Router(name="config")


# Callback data prefix for inline menu buttons. Kept short to leave room for
# the setting key within Telegram's 64-byte limit.
_CB_CONFIG = "cfg:"


# Type alias for FSM entry points — they must accept (message, state) and run
# the relevant dialog. Callback handlers adapt `CallbackQuery` into this shape.
SettingLauncher = Callable[[Message, FSMContext], Awaitable[None]]


@dataclass(frozen=True)
class _Setting:
    """Declarative entry describing one `/config` setting and how to launch it."""

    key: str  # sub-command / callback suffix, e.g. "timezone"
    label: str  # inline button text, e.g. "🕐 Часовой пояс"
    launch: SettingLauncher


# Central registry of available settings. Append here to add a new one — the
# menu, the `/config <key>` dispatcher, and the callback handler all read from
# this list, so no other code needs to change.
_SETTINGS: tuple[_Setting, ...] = (
    _Setting(key="timezone", label="🕐 Часовой пояс", launch=start_timezone_setup),
)


def _settings_by_key() -> dict[str, _Setting]:
    """Index registered settings by their key for O(1) dispatch."""
    return {s.key: s for s in _SETTINGS}


def _config_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the inline menu listing every available setting."""
    rows = [
        [InlineKeyboardButton(text=s.label, callback_data=f"{_CB_CONFIG}{s.key}")]
        for s in _SETTINGS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("config"))
async def cmd_config(
    message: Message,
    command: CommandObject,
    state: FSMContext,
) -> None:
    """Show the settings menu or dispatch to a sub-command like `/config timezone`."""
    raw = (command.args or "").strip().split(maxsplit=1)
    arg = raw[0].lower() if raw else ""

    if not arg:
        await message.answer(
            "Настройки. Выбери, что хочешь изменить:",
            reply_markup=_config_menu_keyboard(),
        )
        return

    setting = _settings_by_key().get(arg)
    if setting is None:
        await message.answer(
            "Неизвестная настройка. Отправь /config без аргументов, чтобы увидеть список."
        )
        return

    await setting.launch(message, state)


@router.callback_query(F.data.startswith(_CB_CONFIG))
async def cb_config_pick(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle a tap on the settings menu — launch the selected setting's FSM."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    if not isinstance(callback.message, Message):
        return

    key = callback.data.removeprefix(_CB_CONFIG)
    setting = _settings_by_key().get(key)
    if setting is None:
        return

    await setting.launch(callback.message, state)
