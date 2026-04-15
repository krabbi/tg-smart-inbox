from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.config import Config
from bot.handlers.commands import (
    _HELP_KEYBOARD,
    WELCOME_TEXT,
    _build_help_text,
    cb_help,
    cmd_help,
    cmd_start,
)
from bot.handlers.messages import handle_document, handle_photo, handle_text
from bot.services.user_settings_service import UserSettingsService


def _make_config(
    groq_api_key: str = "",
    google_drive_folder_id: str = "",
) -> Config:
    """Create a Config for testing with optional features toggled."""
    return Config(
        telegram_bot_token="1234567890:AAFakeTokenForTestingPurposesOnly",
        anthropic_api_key="sk-ant-fake-key-for-testing",
        database_url="sqlite+aiosqlite:///:memory:",
        allowed_user_ids=[123456789],
        groq_api_key=groq_api_key,
        google_drive_folder_id=google_drive_folder_id,
    )


def make_message(text: str | None = None, user_id: int = 123, forwarded: bool = False) -> Message:
    """Create a minimal mock Message."""
    user = MagicMock(spec=User)
    user.id = user_id
    message = MagicMock(spec=Message)
    message.from_user = user
    message.text = text
    message.forward_origin = MagicMock() if forwarded else None
    message.answer = AsyncMock()
    return message


def _make_callback() -> CallbackQuery:
    """Create a minimal mock CallbackQuery."""
    user = MagicMock(spec=User)
    user.id = 123
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = user
    cb.data = "help"
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.answer = AsyncMock()
    return cb


def _make_fsm_state() -> MagicMock:
    """Build a mock FSMContext with async methods stubbed."""
    state = MagicMock(spec=FSMContext)
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    return state


def _make_tz_service(has_tz: bool = True) -> MagicMock:
    """Build a mock UserSettingsService with `has_timezone` wired."""
    svc = MagicMock(spec=UserSettingsService)
    svc.has_timezone = AsyncMock(return_value=has_tz)
    svc.set_timezone = AsyncMock()
    return svc


async def test_cmd_start_sends_welcome_when_tz_set() -> None:
    message = make_message()
    state = _make_fsm_state()
    await cmd_start(message, state=state, user_settings_service=_make_tz_service(has_tz=True))
    message.answer.assert_awaited_once()
    call_text = message.answer.call_args[0][0]
    assert "привет" in call_text.lower()


async def test_cmd_start_includes_commands_when_tz_set() -> None:
    message = make_message()
    state = _make_fsm_state()
    await cmd_start(message, state=state, user_settings_service=_make_tz_service(has_tz=True))
    call_text = message.answer.call_args[0][0]
    for cmd in ["/list", "/search", "/reminders", "/ideas", "/help", "/cancel"]:
        assert cmd in call_text, f"{cmd} not found in /start message"


async def test_cmd_start_has_help_button_when_tz_set() -> None:
    message = make_message()
    state = _make_fsm_state()
    await cmd_start(message, state=state, user_settings_service=_make_tz_service(has_tz=True))
    _, kwargs = message.answer.call_args
    assert kwargs.get("reply_markup") is _HELP_KEYBOARD


async def test_cmd_start_triggers_tz_setup_when_not_set() -> None:
    message = make_message()
    state = _make_fsm_state()
    svc = _make_tz_service(has_tz=False)
    await cmd_start(message, state=state, user_settings_service=svc)
    svc.has_timezone.assert_awaited_once_with(message.from_user.id)
    # FSM entered and continent picker sent
    state.set_state.assert_awaited()
    message.answer.assert_awaited_once()
    call_text = message.answer.call_args[0][0]
    assert "часовой пояс" in call_text.lower()


async def test_cmd_start_fallback_when_service_missing() -> None:
    message = make_message()
    state = _make_fsm_state()
    await cmd_start(message, state=state, user_settings_service=None)
    # Should still send the welcome message so the bot is not silent.
    message.answer.assert_awaited_once()
    assert message.answer.call_args[0][0] == WELCOME_TEXT


async def test_cmd_help_shows_detailed_guide() -> None:
    message = make_message()
    config = _make_config()
    await cmd_help(message, config=config)
    message.answer.assert_awaited_once()
    call_text = message.answer.call_args[0][0]
    assert "Подробная справка" in call_text
    assert "что поделать?" in call_text
    assert "/list" in call_text


async def test_cmd_help_without_config_falls_back() -> None:
    message = make_message()
    await cmd_help(message, config=None)
    message.answer.assert_awaited_once()
    call_text = message.answer.call_args[0][0]
    assert call_text == WELCOME_TEXT


async def test_build_help_text_hides_voice_when_not_configured() -> None:
    config = _make_config(groq_api_key="")
    text = _build_help_text(config)
    assert "Голосовые сообщения" not in text


async def test_build_help_text_shows_voice_when_configured() -> None:
    config = _make_config(groq_api_key="gsk_fake_key")
    text = _build_help_text(config)
    assert "Голосовые сообщения" in text


async def test_build_help_text_hides_drive_when_not_configured() -> None:
    config = _make_config(google_drive_folder_id="")
    text = _build_help_text(config)
    assert "Фото и файлы" not in text


async def test_build_help_text_shows_drive_when_configured() -> None:
    config = _make_config(google_drive_folder_id="folder123")
    text = _build_help_text(config)
    assert "Фото и файлы" in text


async def test_build_help_text_shows_all_optional_features() -> None:
    config = _make_config(groq_api_key="gsk_key", google_drive_folder_id="folder123")
    text = _build_help_text(config)
    assert "Голосовые сообщения" in text
    assert "Фото и файлы" in text


async def test_cb_help_sends_detailed_guide() -> None:
    cb = _make_callback()
    config = _make_config()
    await cb_help(cb, config=config)
    cb.answer.assert_awaited_once()
    cb.message.answer.assert_awaited_once()
    call_text = cb.message.answer.call_args[0][0]
    assert "Подробная справка" in call_text


async def test_cb_help_without_config_falls_back() -> None:
    cb = _make_callback()
    await cb_help(cb, config=None)
    cb.answer.assert_awaited_once()
    cb.message.answer.assert_awaited_once()
    call_text = cb.message.answer.call_args[0][0]
    assert call_text == WELCOME_TEXT


async def test_cb_help_no_message_returns_early() -> None:
    cb = _make_callback()
    cb.message = None
    config = _make_config()
    await cb_help(cb, config=config)
    cb.answer.assert_awaited_once()


async def test_handle_text_replies() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    message = make_message(text="Hello bot")
    await handle_text(message, state=state)
    message.answer.assert_awaited_once()


async def test_handle_text_forwarded_replies() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    message = make_message(text="Forwarded text", forwarded=True)
    await handle_text(message, state=state)
    message.answer.assert_awaited_once()


async def test_handle_photo_replies() -> None:
    message = make_message()
    await handle_photo(message)
    message.answer.assert_awaited_once()
    assert "Фото" in message.answer.call_args[0][0]


async def test_handle_document_replies() -> None:
    message = make_message()
    await handle_document(message)
    message.answer.assert_awaited_once()
    assert "Файл" in message.answer.call_args[0][0]


async def test_handle_text_without_user() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    message = make_message(text="hi")
    message.from_user = None
    await handle_text(message, state=state)
    message.answer.assert_awaited_once()
