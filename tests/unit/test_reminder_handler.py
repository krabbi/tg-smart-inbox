import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.exceptions import TimeParseError
from bot.handlers.reminders import (
    ReminderStates,
    cb_remind_ack,
    cb_remind_snooze,
    cb_task_remind,
    receive_reminder_time,
    task_remind_keyboard,
)
from bot.services.link_service import LinkService
from bot.services.reminder_service import ReminderService
from bot.services.time_parser import TimeParser
from bot.services.user_settings_service import UserSettingsService


def make_message(text: str = "test", user_id: int = 1) -> Message:
    user = MagicMock(spec=User)
    user.id = user_id
    msg = MagicMock(spec=Message)
    msg.from_user = user
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def make_callback(data: str) -> CallbackQuery:
    msg = MagicMock()
    msg.answer = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.message = msg
    cb.answer = AsyncMock()
    return cb


def make_state(data: dict | None = None) -> FSMContext:
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(return_value=data or {})
    return state


# ── task_remind_keyboard ────────────────────────────────────────────────────


def test_task_remind_keyboard_has_item_id() -> None:
    """Keyboard button stores item_id in callback_data."""
    item_id = str(uuid.uuid4())
    kb = task_remind_keyboard(item_id, lang="ru")
    assert len(kb.inline_keyboard) == 1
    btn = kb.inline_keyboard[0][0]
    assert btn.callback_data == f"task_remind:{item_id}"
    assert "Напомнить" in btn.text


# ── cb_task_remind ──────────────────────────────────────────────────────────


async def test_cb_task_remind_enters_fsm() -> None:
    """Pressing 'Remind' button on task enters FSM waiting_for_time."""
    item_id = str(uuid.uuid4())
    cb = make_callback(f"task_remind:{item_id}")
    state = make_state()

    await cb_task_remind(cb, state)

    cb.answer.assert_awaited_once()
    cb.message.edit_reply_markup.assert_awaited_once()
    state.set_state.assert_awaited_once_with(ReminderStates.waiting_for_time)
    state.update_data.assert_awaited_once()
    stored = state.update_data.call_args[0][0]
    assert stored["reminder_item_id"] == item_id
    assert stored["reminder_attempts"] == 0
    cb.message.answer.assert_awaited_once()


async def test_cb_task_remind_no_message_returns_early() -> None:
    """When callback.message is None, only answer() is called."""
    item_id = str(uuid.uuid4())
    cb = make_callback(f"task_remind:{item_id}")
    cb.message = None
    state = make_state()

    await cb_task_remind(cb, state)

    cb.answer.assert_awaited_once()
    state.set_state.assert_not_awaited()


# ── receive_reminder_time ───────────────────────────────────────────────────


async def test_receive_reminder_time_no_services() -> None:
    msg = make_message("завтра в 10")
    state = make_state()
    await receive_reminder_time(msg, state, time_parser=None, reminder_service=None)
    msg.answer.assert_awaited_once()
    state.clear.assert_awaited_once()


async def test_receive_reminder_time_success() -> None:
    msg = make_message("завтра в 10")
    item_id = str(uuid.uuid4())
    state = make_state({"reminder_item_id": item_id})

    remind_at = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)
    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(return_value=remind_at)

    svc = MagicMock(spec=ReminderService)
    svc.create = AsyncMock()

    await receive_reminder_time(msg, state, time_parser=time_parser, reminder_service=svc)

    svc.create.assert_awaited_once()
    state.clear.assert_awaited_once()
    msg.answer.assert_awaited_once()
    assert "🔔" in msg.answer.call_args[0][0]


async def test_receive_reminder_time_parse_error() -> None:
    msg = make_message("абракадабра")
    state = make_state({"reminder_item_id": str(uuid.uuid4())})

    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(side_effect=TimeParseError("unparseable"))

    svc = MagicMock(spec=ReminderService)

    await receive_reminder_time(
        msg, state, time_parser=time_parser, reminder_service=svc, lang="ru"
    )

    msg.answer.assert_awaited_once()
    assert "Не смог" in msg.answer.call_args[0][0]
    state.clear.assert_not_called()
    svc.create.assert_not_awaited()


async def test_receive_reminder_time_parse_error_increments_attempts() -> None:
    """Each failed parse increments the attempt counter without clearing state."""
    msg = make_message("непонятно")
    state = make_state({"reminder_item_id": str(uuid.uuid4()), "reminder_attempts": 0})

    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(side_effect=TimeParseError("unparseable"))

    svc = MagicMock(spec=ReminderService)

    await receive_reminder_time(msg, state, time_parser=time_parser, reminder_service=svc)

    state.clear.assert_not_called()
    state.update_data.assert_awaited_once_with({"reminder_attempts": 1})
    assert "1/3" in msg.answer.call_args[0][0]


async def test_receive_reminder_time_aborts_after_max_attempts() -> None:
    """After MAX_ATTEMPTS failures the dialog is cancelled automatically."""
    msg = make_message("непонятно")
    # Already at 2 attempts — this is the 3rd (final)
    state = make_state({"reminder_item_id": str(uuid.uuid4()), "reminder_attempts": 2})

    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(side_effect=TimeParseError("unparseable"))

    svc = MagicMock(spec=ReminderService)

    await receive_reminder_time(
        msg, state, time_parser=time_parser, reminder_service=svc, lang="ru"
    )

    state.clear.assert_awaited_once()
    assert "Не удалось" in msg.answer.call_args[0][0]


async def test_receive_reminder_time_with_url_clears_state_and_delegates_to_link_flow() -> None:
    """A URL sent during the time-input FSM exits the dialog and goes to link flow."""
    url = "https://example.com/article"
    msg = make_message(url)
    state = make_state({"reminder_item_id": str(uuid.uuid4()), "reminder_attempts": 1})

    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock()  # should not be called
    reminder_svc = MagicMock(spec=ReminderService)
    reminder_svc.create = AsyncMock()  # should not be called

    saved_item = MagicMock()
    saved_item.id = uuid.uuid4()
    link_svc = MagicMock(spec=LinkService)
    link_svc.save = AsyncMock(return_value=saved_item)

    await receive_reminder_time(
        msg,
        state,
        time_parser=time_parser,
        reminder_service=reminder_svc,
        link_service=link_svc,
    )

    state.clear.assert_awaited_once()
    time_parser.parse.assert_not_awaited()
    reminder_svc.create.assert_not_awaited()
    link_svc.save.assert_awaited_once_with(url, 1)
    # Link flow replies with the "saved" message + keyboard
    msg.answer.assert_awaited_once()
    assert "reply_markup" in msg.answer.call_args[1]


async def test_receive_reminder_time_with_url_and_no_link_service_replies_unavailable() -> None:
    """If link_service is missing, the FSM still exits and the user sees a polite message."""
    msg = make_message("смотри https://example.com/x")
    state = make_state({"reminder_item_id": str(uuid.uuid4())})

    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock()
    reminder_svc = MagicMock(spec=ReminderService)

    await receive_reminder_time(
        msg,
        state,
        time_parser=time_parser,
        reminder_service=reminder_svc,
        link_service=None,
        lang="ru",
    )

    state.clear.assert_awaited_once()
    time_parser.parse.assert_not_awaited()
    msg.answer.assert_awaited_once()
    assert "недоступен" in msg.answer.call_args[0][0].lower()


async def test_receive_reminder_time_with_url_embedded_in_sentence() -> None:
    """A URL embedded in arbitrary text is still detected and routed to the link flow."""
    msg = make_message("посмотри вот это https://example.com/a, пожалуйста")
    state = make_state({"reminder_item_id": str(uuid.uuid4())})

    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock()
    reminder_svc = MagicMock(spec=ReminderService)

    saved_item = MagicMock()
    saved_item.id = uuid.uuid4()
    link_svc = MagicMock(spec=LinkService)
    link_svc.save = AsyncMock(return_value=saved_item)

    await receive_reminder_time(
        msg,
        state,
        time_parser=time_parser,
        reminder_service=reminder_svc,
        link_service=link_svc,
    )

    state.clear.assert_awaited_once()
    time_parser.parse.assert_not_awaited()
    # URL passed to link_service is the extracted one (trailing comma stripped by regex? actually \S+ greedy)
    saved_url = link_svc.save.call_args[0][0]
    assert saved_url.startswith("https://example.com/a")


async def test_receive_reminder_time_uses_user_timezone() -> None:
    """User's timezone from UserSettingsService is forwarded to TimeParser.parse."""
    msg = make_message("завтра в 10", user_id=42)
    item_id = str(uuid.uuid4())
    state = make_state({"reminder_item_id": item_id})

    remind_at = datetime(2026, 6, 2, 7, 0, tzinfo=UTC)
    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(return_value=remind_at)

    reminder_svc = MagicMock(spec=ReminderService)
    reminder_svc.create = AsyncMock()

    settings_svc = MagicMock(spec=UserSettingsService)
    settings_svc.get_timezone = AsyncMock(return_value="Europe/Moscow")

    await receive_reminder_time(
        msg,
        state,
        time_parser=time_parser,
        reminder_service=reminder_svc,
        user_settings_service=settings_svc,
    )

    settings_svc.get_timezone.assert_awaited_once_with(42)
    time_parser.parse.assert_awaited_once()
    assert time_parser.parse.call_args.kwargs["user_tz"] == "Europe/Moscow"
    reminder_svc.create.assert_awaited_once()
    # Confirmation message is formatted in the user's timezone
    # (07:00 UTC on 2026-06-02 → 10:00 MSK).
    answer_text = msg.answer.call_args[0][0]
    assert "02.06.2026 10:00 MSK" in answer_text
    assert "UTC" not in answer_text


async def test_receive_reminder_time_save_error() -> None:
    msg = make_message("завтра в 10")
    item_id = str(uuid.uuid4())
    state = make_state({"reminder_item_id": item_id})

    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(return_value=datetime(2026, 6, 2, tzinfo=UTC))

    svc = MagicMock(spec=ReminderService)
    svc.create = AsyncMock(side_effect=Exception("DB error"))

    await receive_reminder_time(
        msg, state, time_parser=time_parser, reminder_service=svc, lang="ru"
    )

    msg.answer.assert_awaited_once()
    assert "Не удалось" in msg.answer.call_args[0][0]
    state.clear.assert_awaited_once()


# ── snooze / ack callbacks ──────────────────────────────────────────────────


def make_callback_with_user(data: str, user_id: int = 1) -> CallbackQuery:
    msg = MagicMock()
    msg.answer = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    user = MagicMock()
    user.id = user_id
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.message = msg
    cb.answer = AsyncMock()
    cb.from_user = user
    return cb


async def test_cb_remind_snooze_1h_calls_snooze() -> None:
    reminder_id = str(uuid.uuid4())
    cb = make_callback_with_user(f"remind_snooze:1h:{reminder_id}", user_id=5)

    svc = MagicMock(spec=ReminderService)
    svc.snooze = AsyncMock(return_value=True)

    await cb_remind_snooze(cb, reminder_service=svc, lang="ru")

    svc.snooze.assert_awaited_once()
    call_kwargs = svc.snooze.call_args[1]
    assert call_kwargs["reminder_id"] == uuid.UUID(reminder_id)
    assert call_kwargs["user_id"] == 5
    cb.message.edit_reply_markup.assert_awaited_once()
    cb.message.answer.assert_awaited_once()
    assert "1 час" in cb.message.answer.call_args[0][0]


async def test_cb_remind_snooze_uses_user_timezone() -> None:
    """Snooze confirmation message uses the user's configured timezone."""
    reminder_id = str(uuid.uuid4())
    cb = make_callback_with_user(f"remind_snooze:1h:{reminder_id}", user_id=42)

    svc = MagicMock(spec=ReminderService)
    svc.snooze = AsyncMock(return_value=True)

    settings_svc = MagicMock(spec=UserSettingsService)
    settings_svc.get_timezone = AsyncMock(return_value="Europe/Moscow")

    await cb_remind_snooze(cb, reminder_service=svc, user_settings_service=settings_svc)

    settings_svc.get_timezone.assert_awaited_once_with(42)
    answer_text = cb.message.answer.call_args[0][0]
    # Confirmation contains the MSK label (or numeric IANA fallback) — the abbreviation
    # is preferred when zoneinfo exposes one.
    assert "MSK" in answer_text


async def test_cb_remind_snooze_1d_calls_snooze() -> None:
    reminder_id = str(uuid.uuid4())
    cb = make_callback_with_user(f"remind_snooze:1d:{reminder_id}", user_id=5)

    svc = MagicMock(spec=ReminderService)
    svc.snooze = AsyncMock(return_value=True)

    await cb_remind_snooze(cb, reminder_service=svc, lang="ru")

    assert "1 день" in cb.message.answer.call_args[0][0]
    from datetime import timedelta

    now = datetime.now(UTC)
    remind_at = svc.snooze.call_args[1]["remind_at"]
    diff = remind_at - now
    assert timedelta(hours=23) < diff < timedelta(hours=25)


async def test_cb_remind_snooze_not_owned_sends_message() -> None:
    reminder_id = str(uuid.uuid4())
    cb = make_callback_with_user(f"remind_snooze:1h:{reminder_id}")

    svc = MagicMock(spec=ReminderService)
    svc.snooze = AsyncMock(return_value=False)

    await cb_remind_snooze(cb, reminder_service=svc, lang="ru")

    cb.message.answer.assert_awaited_once()
    assert "не найдено" in cb.message.answer.call_args[0][0].lower()


async def test_cb_remind_snooze_no_service_replies_unavailable() -> None:
    reminder_id = str(uuid.uuid4())
    cb = make_callback_with_user(f"remind_snooze:1h:{reminder_id}")

    await cb_remind_snooze(cb, reminder_service=None, lang="ru")

    cb.message.answer.assert_awaited_once()
    assert "недоступен" in cb.message.answer.call_args[0][0].lower()


async def test_cb_remind_ack_acknowledges_reminder() -> None:
    reminder_id = str(uuid.uuid4())
    cb = make_callback_with_user(f"remind_ack:{reminder_id}", user_id=7)
    cb.message.html_text = "🔔 Напоминание:\nкупить молоко"
    cb.message.edit_text = AsyncMock()

    svc = MagicMock(spec=ReminderService)
    svc.acknowledge = AsyncMock(return_value=True)

    await cb_remind_ack(cb, reminder_service=svc, lang="ru")

    svc.acknowledge.assert_awaited_once_with(reminder_id=uuid.UUID(reminder_id), user_id=7)
    cb.message.edit_text.assert_awaited_once()
    call_args = cb.message.edit_text.call_args
    assert "Выполнено" in call_args[0][0]
    assert "🔔 Напоминание:\nкупить молоко" in call_args[0][0]
    assert call_args[1]["reply_markup"] is None
    assert call_args[1]["parse_mode"] == "HTML"


async def test_cb_remind_ack_falls_back_to_text_when_no_html_text() -> None:
    reminder_id = str(uuid.uuid4())
    cb = make_callback_with_user(f"remind_ack:{reminder_id}", user_id=7)
    cb.message.html_text = None
    cb.message.text = "🔔 Напоминание:\nкупить молоко"
    cb.message.edit_text = AsyncMock()

    svc = MagicMock(spec=ReminderService)
    svc.acknowledge = AsyncMock(return_value=True)

    await cb_remind_ack(cb, reminder_service=svc, lang="ru")

    call_args = cb.message.edit_text.call_args
    assert "купить молоко" in call_args[0][0]
    assert "Выполнено" in call_args[0][0]


async def test_cb_remind_ack_no_service_replies_unavailable() -> None:
    reminder_id = str(uuid.uuid4())
    cb = make_callback_with_user(f"remind_ack:{reminder_id}")

    await cb_remind_ack(cb, reminder_service=None, lang="ru")

    cb.message.answer.assert_awaited_once()
    assert "недоступен" in cb.message.answer.call_args[0][0].lower()


async def test_cb_remind_ack_no_message_returns_early() -> None:
    """When callback.message is None, only answer() is called."""
    cb = make_callback_with_user(f"remind_ack:{uuid.uuid4()}")
    cb.message = None

    svc = MagicMock(spec=ReminderService)
    svc.acknowledge = AsyncMock()

    await cb_remind_ack(cb, reminder_service=svc)

    cb.answer.assert_awaited_once()
    svc.acknowledge.assert_not_awaited()


async def test_cb_remind_ack_no_from_user_returns_early() -> None:
    """When callback.from_user is None, only answer() is called."""
    cb = make_callback_with_user(f"remind_ack:{uuid.uuid4()}")
    cb.from_user = None

    svc = MagicMock(spec=ReminderService)
    svc.acknowledge = AsyncMock()

    await cb_remind_ack(cb, reminder_service=svc)

    cb.answer.assert_awaited_once()
    svc.acknowledge.assert_not_awaited()


async def test_cb_remind_ack_service_error_replies_error() -> None:
    """When acknowledge raises, reply with error and do not call edit_text."""
    reminder_id = str(uuid.uuid4())
    cb = make_callback_with_user(f"remind_ack:{reminder_id}", user_id=7)
    cb.message.edit_text = AsyncMock()

    svc = MagicMock(spec=ReminderService)
    svc.acknowledge = AsyncMock(side_effect=Exception("db error"))

    await cb_remind_ack(cb, reminder_service=svc, lang="ru")

    cb.message.answer.assert_awaited_once()
    assert "Не удалось" in cb.message.answer.call_args[0][0]
    cb.message.edit_text.assert_not_awaited()
