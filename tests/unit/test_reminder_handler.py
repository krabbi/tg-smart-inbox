import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.exceptions import TimeParseError
from bot.handlers.reminders import (
    ReminderStates,
    ask_reminder,
    cb_remind_no,
    cb_remind_yes,
    receive_reminder_time,
)
from bot.services.reminder_service import ReminderService
from bot.services.time_parser import TimeParser


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


async def test_ask_reminder_sends_keyboard() -> None:
    msg = make_message()
    state = make_state()
    item_id = str(uuid.uuid4())
    await ask_reminder(msg, "купить молоко", item_id, state)
    msg.answer.assert_awaited_once()
    call_kwargs = msg.answer.call_args[1]
    assert "reply_markup" in call_kwargs


async def test_cb_remind_yes_sets_state() -> None:
    cb = make_callback("remind:yes")
    state = make_state()
    await cb_remind_yes(cb, state)
    state.set_state.assert_awaited_once_with(ReminderStates.waiting_for_time)
    cb.message.answer.assert_awaited_once()


async def test_cb_remind_no_clears_state() -> None:
    cb = make_callback("remind:no")
    state = make_state()
    await cb_remind_no(cb, state)
    state.clear.assert_awaited_once()
    cb.message.answer.assert_awaited_once()


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

    await receive_reminder_time(msg, state, time_parser=time_parser, reminder_service=svc)

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

    await receive_reminder_time(msg, state, time_parser=time_parser, reminder_service=svc)

    state.clear.assert_awaited_once()
    assert "Не удалось" in msg.answer.call_args[0][0]


async def test_cb_remind_yes_resets_attempt_counter() -> None:
    """Confirming a reminder resets the attempt counter to 0."""
    cb = make_callback("remind:yes")
    state = make_state()
    await cb_remind_yes(cb, state)
    state.update_data.assert_awaited_once_with({"reminder_attempts": 0})


async def test_receive_reminder_time_save_error() -> None:
    msg = make_message("завтра в 10")
    item_id = str(uuid.uuid4())
    state = make_state({"reminder_item_id": item_id})

    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(return_value=datetime(2026, 6, 2, tzinfo=UTC))

    svc = MagicMock(spec=ReminderService)
    svc.create = AsyncMock(side_effect=Exception("DB error"))

    await receive_reminder_time(msg, state, time_parser=time_parser, reminder_service=svc)

    msg.answer.assert_awaited_once()
    assert "Не удалось" in msg.answer.call_args[0][0]
    state.clear.assert_awaited_once()
