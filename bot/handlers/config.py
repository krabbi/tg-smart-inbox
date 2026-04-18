"""`/config` command: user-facing settings menu and sub-commands.

The command is designed to be extensible: each setting is declared once in
`_SETTINGS` (label key, sub-command, FSM launcher). Adding a new setting — e.g.
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

from bot.exceptions import InvalidLanguageError
from bot.handlers.timezone_setup import start_timezone_setup
from bot.i18n import SUPPORTED_LANGUAGES, t
from bot.services.user_settings_service import UserSettingsService

router = Router(name="config")


# Callback data prefix for inline menu buttons. Kept short to leave room for
# the setting key within Telegram's 64-byte limit.
_CB_CONFIG = "cfg:"
_CB_LANGUAGE = "cfglang:"


# Type alias for FSM entry points — they must accept (message, state) and run
# the relevant dialog. Callback handlers adapt `CallbackQuery` into this shape.
SettingLauncher = Callable[[Message, FSMContext, str], Awaitable[None]]


@dataclass(frozen=True)
class _Setting:
    """Declarative entry describing one `/config` setting and how to launch it."""

    key: str  # sub-command / callback suffix, e.g. "timezone"
    label_key: str  # i18n key for the inline button label
    launch: SettingLauncher


async def _launch_timezone(message: Message, state: FSMContext, lang: str) -> None:
    """Adapter that routes the timezone setting launcher to its handler."""
    await start_timezone_setup(message, state, lang)


async def _launch_language(message: Message, state: FSMContext, lang: str) -> None:
    """Show the language picker inline keyboard for the /config language sub-command."""
    await message.answer(t("language_choose", lang), reply_markup=_language_keyboard(lang))


# Central registry of available settings. Append here to add a new one — the
# menu, the `/config <key>` dispatcher, and the callback handler all read from
# this list, so no other code needs to change.
_SETTINGS: tuple[_Setting, ...] = (
    _Setting(key="timezone", label_key="config_btn_timezone", launch=_launch_timezone),
    _Setting(key="language", label_key="config_btn_language", launch=_launch_language),
)


def _settings_by_key() -> dict[str, _Setting]:
    """Index registered settings by their key for O(1) dispatch."""
    return {s.key: s for s in _SETTINGS}


def _config_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the inline menu listing every available setting, localized to ``lang``."""
    rows = [
        [InlineKeyboardButton(text=t(s.label_key, lang), callback_data=f"{_CB_CONFIG}{s.key}")]
        for s in _SETTINGS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _language_keyboard(current: str) -> InlineKeyboardMarkup:
    """Build the language picker with the current language marked by a check."""
    mark = t("language_btn_current_mark", current)
    rows = [
        [
            InlineKeyboardButton(
                text=t("language_btn_ru", current) + (mark if current == "ru" else ""),
                callback_data=f"{_CB_LANGUAGE}ru",
            ),
            InlineKeyboardButton(
                text=t("language_btn_en", current) + (mark if current == "en" else ""),
                callback_data=f"{_CB_LANGUAGE}en",
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("config"))
async def cmd_config(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    lang: str = "en",
) -> None:
    """Show the settings menu or dispatch to a sub-command like `/config timezone`."""
    raw = (command.args or "").strip().split(maxsplit=1)
    arg = raw[0].lower() if raw else ""

    if not arg:
        await message.answer(
            t("config_menu_title", lang),
            reply_markup=_config_menu_keyboard(lang),
        )
        return

    setting = _settings_by_key().get(arg)
    if setting is None:
        await message.answer(t("config_unknown_setting", lang))
        return

    await setting.launch(message, state, lang)


@router.callback_query(F.data.startswith(_CB_CONFIG))
async def cb_config_pick(
    callback: CallbackQuery,
    state: FSMContext,
    lang: str = "en",
) -> None:
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

    await setting.launch(callback.message, state, lang)


@router.callback_query(F.data.startswith(_CB_LANGUAGE))
async def cb_config_language(
    callback: CallbackQuery,
    user_settings_service: UserSettingsService | None = None,
    lang: str = "en",
) -> None:
    """Persist the selected interface language and confirm in the new language."""
    await callback.answer()
    if callback.message is None or callback.data is None or callback.from_user is None:
        return
    if not isinstance(callback.message, Message):
        return

    choice = callback.data.removeprefix(_CB_LANGUAGE)
    if choice not in SUPPORTED_LANGUAGES:
        return

    if user_settings_service is None:
        await callback.message.edit_text(
            t("language_settings_service_unavailable", lang),
            reply_markup=None,
        )
        return

    try:
        await user_settings_service.set_language(callback.from_user.id, choice)
    except InvalidLanguageError:
        await callback.message.edit_text(
            t("language_save_failed", lang),
            reply_markup=_language_keyboard(lang),
        )
        return

    await callback.message.edit_text(
        t("language_saved", choice),
        reply_markup=None,
    )
