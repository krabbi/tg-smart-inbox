import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.config import Config
from bot.handlers.commands import (
    _build_help_text,
    _help_keyboard,
    cb_help,
    cmd_help,
    cmd_start,
)
from bot.handlers.messages import handle_document, handle_photo, handle_text
from bot.i18n import t
from bot.models.item import Item, ItemType
from bot.services.drive_service import DriveFile
from bot.services.media_service import MediaResult, MediaService
from bot.services.user_settings_service import UserSettingsService
from bot.services.vision_service import MediaAnalysis


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


def make_message(
    text: str | None = None,
    user_id: int = 123,
    forwarded: bool = False,
    language_code: str | None = "en",
) -> Message:
    """Create a minimal mock Message."""
    user = MagicMock(spec=User)
    user.id = user_id
    user.language_code = language_code
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
    """Build a mock UserSettingsService with `has_timezone` and `ensure_user_settings` wired."""
    svc = MagicMock(spec=UserSettingsService)
    svc.has_timezone = AsyncMock(return_value=has_tz)
    svc.set_timezone = AsyncMock()
    svc.ensure_user_settings = AsyncMock()
    return svc


async def test_cmd_start_sends_welcome_when_tz_set() -> None:
    message = make_message()
    state = _make_fsm_state()
    await cmd_start(
        message, state=state, user_settings_service=_make_tz_service(has_tz=True), lang="ru"
    )
    message.answer.assert_awaited_once()
    call_text = message.answer.call_args[0][0]
    assert "привет" in call_text.lower()


async def test_cmd_start_includes_commands_when_tz_set() -> None:
    message = make_message()
    state = _make_fsm_state()
    await cmd_start(
        message, state=state, user_settings_service=_make_tz_service(has_tz=True), lang="ru"
    )
    call_text = message.answer.call_args[0][0]
    for cmd in ["/list", "/search", "/reminders", "/ideas", "/help", "/cancel"]:
        assert cmd in call_text, f"{cmd} not found in /start message"


async def test_cmd_start_has_help_button_when_tz_set() -> None:
    message = make_message()
    state = _make_fsm_state()
    await cmd_start(
        message, state=state, user_settings_service=_make_tz_service(has_tz=True), lang="ru"
    )
    _, kwargs = message.answer.call_args
    assert kwargs.get("reply_markup") == _help_keyboard("ru")


async def test_cmd_start_triggers_tz_setup_when_not_set() -> None:
    message = make_message()
    state = _make_fsm_state()
    svc = _make_tz_service(has_tz=False)
    await cmd_start(message, state=state, user_settings_service=svc, lang="ru")
    svc.has_timezone.assert_awaited_once_with(message.from_user.id)
    # FSM entered and continent picker sent
    state.set_state.assert_awaited()
    message.answer.assert_awaited_once()
    call_text = message.answer.call_args[0][0]
    assert "часовой пояс" in call_text.lower()


async def test_cmd_start_fallback_when_service_missing() -> None:
    message = make_message()
    state = _make_fsm_state()
    await cmd_start(message, state=state, user_settings_service=None, lang="ru")
    # Should still send the welcome message so the bot is not silent.
    message.answer.assert_awaited_once()
    assert message.answer.call_args[0][0] == t("welcome", "ru")


async def test_cmd_help_shows_detailed_guide() -> None:
    message = make_message()
    config = _make_config()
    await cmd_help(message, config=config, lang="ru")
    message.answer.assert_awaited_once()
    call_text = message.answer.call_args[0][0]
    assert "Подробная справка" in call_text
    assert "что поделать?" in call_text
    assert "/list" in call_text


async def test_cmd_help_without_config_falls_back() -> None:
    message = make_message()
    await cmd_help(message, config=None, lang="ru")
    message.answer.assert_awaited_once()
    call_text = message.answer.call_args[0][0]
    assert call_text == t("welcome", "ru")


async def test_build_help_text_hides_voice_when_not_configured() -> None:
    config = _make_config(groq_api_key="")
    text = _build_help_text(config, "ru")
    assert "Голосовые сообщения" not in text


async def test_build_help_text_shows_voice_when_configured() -> None:
    config = _make_config(groq_api_key="gsk_fake_key")
    text = _build_help_text(config, "ru")
    assert "Голосовые сообщения" in text


async def test_build_help_text_hides_drive_when_not_configured() -> None:
    config = _make_config(google_drive_folder_id="")
    text = _build_help_text(config, "ru")
    assert "Фото и файлы" not in text


async def test_build_help_text_shows_drive_when_configured() -> None:
    config = _make_config(google_drive_folder_id="folder123")
    text = _build_help_text(config, "ru")
    assert "Фото и файлы" in text


async def test_build_help_text_shows_all_optional_features() -> None:
    config = _make_config(groq_api_key="gsk_key", google_drive_folder_id="folder123")
    text = _build_help_text(config, "ru")
    assert "Голосовые сообщения" in text
    assert "Фото и файлы" in text


async def test_cb_help_sends_detailed_guide() -> None:
    cb = _make_callback()
    config = _make_config()
    await cb_help(cb, config=config, lang="ru")
    cb.answer.assert_awaited_once()
    cb.message.answer.assert_awaited_once()
    call_text = cb.message.answer.call_args[0][0]
    assert "Подробная справка" in call_text


async def test_cb_help_without_config_falls_back() -> None:
    cb = _make_callback()
    await cb_help(cb, config=None, lang="ru")
    cb.answer.assert_awaited_once()
    cb.message.answer.assert_awaited_once()
    call_text = cb.message.answer.call_args[0][0]
    assert call_text == t("welcome", "ru")


async def test_cb_help_no_message_returns_early() -> None:
    cb = _make_callback()
    cb.message = None
    config = _make_config()
    await cb_help(cb, config=config, lang="ru")
    cb.answer.assert_awaited_once()


async def test_handle_text_replies() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    message = make_message(text="Hello bot")
    await handle_text(message, state=state, lang="ru")
    message.answer.assert_awaited_once()


async def test_handle_text_forwarded_replies() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    message = make_message(text="Forwarded text", forwarded=True)
    await handle_text(message, state=state, lang="ru")
    message.answer.assert_awaited_once()


async def test_handle_photo_replies() -> None:
    message = make_message()
    await handle_photo(message, lang="ru")
    message.answer.assert_awaited_once()
    assert "Фото" in message.answer.call_args[0][0]


async def test_handle_document_replies() -> None:
    message = make_message()
    await handle_document(message, lang="ru")
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
    await handle_text(message, state=state, lang="ru")
    message.answer.assert_awaited_once()


def _make_media_message_with_photo(user_id: int = 555) -> Message:
    """Build a Message mock with a single photo and a stubbed bot for downloads."""
    message = make_message(user_id=user_id)
    photo = MagicMock()
    photo.file_id = "FILE_ID_PHOTO"
    message.photo = [photo]

    file = MagicMock()
    file.file_path = "photos/file.jpg"
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=file)
    bot.download_file = AsyncMock(return_value=BytesIO(b"jpeg-bytes"))
    message.bot = bot
    return message


def _make_media_message_with_document(user_id: int = 555, mime_type: str = "image/png") -> Message:
    """Build a Message mock with a document and a stubbed bot for downloads."""
    message = make_message(user_id=user_id)
    doc = MagicMock()
    doc.file_id = "FILE_ID_DOC"
    doc.file_name = "report.pdf"
    doc.mime_type = mime_type
    message.document = doc

    file = MagicMock()
    file.file_path = "files/report.pdf"
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=file)
    bot.download_file = AsyncMock(return_value=BytesIO(b"doc-bytes"))
    message.bot = bot
    return message


def _make_media_service_mock() -> MagicMock:
    """Build a MediaService mock that returns a predictable MediaResult."""
    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.type = ItemType.media
    item.description = "stub"
    drive_file = DriveFile(file_id="x", name="x", web_link="https://drive.google.com/x")
    analysis = MediaAnalysis(category="photo", description="stub")
    result = MediaResult(item=item, analysis=analysis, drive_file=drive_file)

    svc = MagicMock(spec=MediaService)
    svc.process = AsyncMock(return_value=result)
    return svc


async def test_handle_photo_passes_user_id_to_media_service() -> None:
    """``message.from_user.id`` must reach MediaService.process unchanged."""
    media_service = _make_media_service_mock()
    message = _make_media_message_with_photo(user_id=42)

    await handle_photo(message, media_service=media_service, lang="ru")

    media_service.process.assert_awaited_once()
    kwargs = media_service.process.await_args.kwargs
    assert kwargs["user_id"] == 42


async def test_handle_document_passes_user_id_to_media_service() -> None:
    """Documents must propagate ``message.from_user.id`` into MediaService.process."""
    media_service = _make_media_service_mock()
    message = _make_media_message_with_document(user_id=99)

    await handle_document(message, media_service=media_service, lang="ru")

    media_service.process.assert_awaited_once()
    kwargs = media_service.process.await_args.kwargs
    assert kwargs["user_id"] == 99


async def test_handle_photo_drops_anonymous_message_without_calling_service() -> None:
    """No ``from_user`` → never call MediaService (would otherwise mix Drive folders)."""
    media_service = _make_media_service_mock()
    message = _make_media_message_with_photo()
    message.from_user = None

    await handle_photo(message, media_service=media_service, lang="ru")

    media_service.process.assert_not_awaited()
    message.answer.assert_not_awaited()


async def test_handle_document_drops_anonymous_message_without_calling_service() -> None:
    """No ``from_user`` → never call MediaService (would otherwise mix Drive folders)."""
    media_service = _make_media_service_mock()
    message = _make_media_message_with_document()
    message.from_user = None

    await handle_document(message, media_service=media_service, lang="ru")

    media_service.process.assert_not_awaited()
    message.answer.assert_not_awaited()


# ── /start onboarding & settings creation ────────────────────────────────────


async def test_cmd_start_ensures_settings_for_returning_user() -> None:
    """/start calls ensure_user_settings for a returning user (timezone already set)."""
    message = make_message()
    state = _make_fsm_state()
    svc = _make_tz_service(has_tz=True)

    await cmd_start(message, state=state, user_settings_service=svc, lang="ru")

    svc.ensure_user_settings.assert_awaited_once_with(
        message.from_user.id, message.from_user.language_code
    )
    message.answer.assert_awaited_once()


async def test_cmd_start_does_not_call_ensure_settings_for_new_user() -> None:
    """/start does NOT call ensure_user_settings for a brand-new user (no timezone yet).

    For new users the settings row is created by set_timezone at the end of the
    timezone FSM, not by /start directly — so has_timezone() can continue to
    correctly distinguish 'never configured' from 'explicitly chose UTC'.
    """
    message = make_message()
    state = _make_fsm_state()
    svc = _make_tz_service(has_tz=False)

    await cmd_start(message, state=state, user_settings_service=svc, lang="ru")

    svc.ensure_user_settings.assert_not_awaited()
    # The timezone picker was launched instead.
    state.set_state.assert_awaited()


async def test_cmd_start_does_not_call_ensure_settings_when_service_missing() -> None:
    """/start is safe when user_settings_service is not wired (DI misconfiguration)."""
    message = make_message()
    state = _make_fsm_state()

    # Should not raise; welcome message is sent anyway.
    await cmd_start(message, state=state, user_settings_service=None, lang="en")

    message.answer.assert_awaited_once()


# ── handle_text settings auto-creation ───────────────────────────────────────


async def test_handle_text_calls_ensure_user_settings_before_saving() -> None:
    """handle_text creates per-user settings on the very first message."""
    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    message = make_message(text="buy milk")
    message.from_user.language_code = "ru"

    svc = MagicMock(spec=UserSettingsService)
    svc.ensure_user_settings = AsyncMock()

    await handle_text(message, state=state, user_settings_service=svc, lang="ru")

    svc.ensure_user_settings.assert_awaited_once_with(
        message.from_user.id, message.from_user.language_code
    )


async def test_handle_text_skips_ensure_settings_without_user() -> None:
    """handle_text does not attempt settings creation when from_user is absent."""
    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    message = make_message(text="hello")
    message.from_user = None

    svc = MagicMock(spec=UserSettingsService)
    svc.ensure_user_settings = AsyncMock()

    await handle_text(message, state=state, user_settings_service=svc, lang="en")

    svc.ensure_user_settings.assert_not_awaited()
