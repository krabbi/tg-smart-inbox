import logging
import uuid
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.exceptions import TimeParseError
from bot.services.reminder_service import ReminderService
from bot.services.time_parser import TimeParser

logger = logging.getLogger(__name__)

router = Router(name="reminders")


class ReminderStates(StatesGroup):
    waiting_for_time = State()


_ITEM_ID_KEY = "reminder_item_id"
_TASK_TEXT_KEY = "reminder_task_text"
_ATTEMPTS_KEY = "reminder_attempts"
_MAX_ATTEMPTS = 3

_ASK_REMIND_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data="remind:yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data="remind:no"),
        ]
    ]
)


async def ask_reminder(
    message: Message,
    task_text: str,
    item_id: str,
    state: FSMContext,
) -> None:
    """Ask the user whether to set a reminder. Called from the messages handler."""
    await state.update_data({_ITEM_ID_KEY: item_id, _TASK_TEXT_KEY: task_text})
    await message.answer(
        f"📝 Задача: <b>{task_text}</b>\n\nНапомнить об этом?",
        reply_markup=_ASK_REMIND_KB,
    )


@router.callback_query(F.data == "remind:yes")
async def cb_remind_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """User confirmed reminder — ask for the time."""
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    await state.set_state(ReminderStates.waiting_for_time)
    await state.update_data({_ATTEMPTS_KEY: 0})
    await callback.message.answer(  # type: ignore[union-attr]
        "Когда напомнить? (например: «завтра в 10», «через 2 часа», «в пятницу»)\n"
        "Для отмены — /cancel"
    )


@router.callback_query(F.data == "remind:no")
async def cb_remind_no(callback: CallbackQuery, state: FSMContext) -> None:
    """User declined reminder — clear state."""
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    await state.clear()
    await callback.message.answer("Хорошо, сохранено без напоминания.")  # type: ignore[union-attr]


@router.message(ReminderStates.waiting_for_time)
async def receive_reminder_time(
    message: Message,
    state: FSMContext,
    time_parser: TimeParser | None = None,
    reminder_service: ReminderService | None = None,
) -> None:
    """Parse the user's time expression and create the reminder."""
    if time_parser is None or reminder_service is None:
        await message.answer("Сервис напоминаний временно недоступен.")
        await state.clear()
        return

    data = await state.get_data()
    item_id_str = data.get(_ITEM_ID_KEY, "")

    try:
        remind_at = await time_parser.parse(message.text or "", now=datetime.now(UTC))
    except TimeParseError:
        data = await state.get_data()
        attempts = data.get(_ATTEMPTS_KEY, 0) + 1
        if attempts >= _MAX_ATTEMPTS:
            await state.clear()
            await message.answer(
                "Не удалось разобрать время после нескольких попыток. Напоминание не создано."
            )
            return
        await state.update_data({_ATTEMPTS_KEY: attempts})
        await message.answer(
            f"Не смог понять время ({attempts}/{_MAX_ATTEMPTS}). "
            "Попробуй: «завтра в 10», «через 2 часа», «в пятницу в 15:00»\n"
            "Для отмены — /cancel"
        )
        return

    try:
        item_id = uuid.UUID(item_id_str)
        await reminder_service.create(item_id=item_id, remind_at=remind_at)
    except Exception:
        logger.exception("Failed to save reminder for item %s", item_id_str)
        await message.answer("Не удалось сохранить напоминание.")
        await state.clear()
        return

    await state.clear()
    formatted = remind_at.strftime("%d.%m.%Y %H:%M UTC")
    await message.answer(f"🔔 Напомню {formatted}!")


@router.callback_query(F.data.startswith("remind_snooze:"))
async def cb_remind_snooze(
    callback: CallbackQuery,
    reminder_service: ReminderService | None = None,
) -> None:
    """Snooze a reminder by 1 hour or 1 day."""
    await callback.answer()
    if callback.message is None or callback.from_user is None:
        return

    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        return
    _, period, reminder_id_str = parts

    if period == "1h":
        delta = timedelta(hours=1)
        label = "1 час"
    else:
        delta = timedelta(days=1)
        label = "1 день"

    if reminder_service is None:
        await callback.message.answer("Сервис напоминаний временно недоступен.")
        return

    try:
        reminder_id = uuid.UUID(reminder_id_str)
        remind_at = datetime.now(UTC) + delta
        ok = await reminder_service.snooze(
            reminder_id=reminder_id,
            user_id=callback.from_user.id,
            remind_at=remind_at,
        )
    except Exception:
        logger.exception("Failed to snooze reminder %s", reminder_id_str)
        await callback.message.answer("Не удалось отложить напоминание.")
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    if ok:
        formatted = remind_at.strftime("%d.%m.%Y %H:%M UTC")
        await callback.message.answer(f"⏰ Напомню через {label} ({formatted}).")
    else:
        await callback.message.answer("Напоминание не найдено или уже неактивно.")


@router.callback_query(F.data.startswith("remind_ack:"))
async def cb_remind_ack(
    callback: CallbackQuery,
    reminder_service: ReminderService | None = None,
) -> None:
    """Acknowledge a reminder — user has seen and processed it."""
    await callback.answer()
    if callback.message is None or callback.from_user is None:
        return

    reminder_id_str = (callback.data or "").removeprefix("remind_ack:")

    if reminder_service is None:
        await callback.message.answer("Сервис напоминаний временно недоступен.")
        return

    try:
        reminder_id = uuid.UUID(reminder_id_str)
        await reminder_service.acknowledge(
            reminder_id=reminder_id,
            user_id=callback.from_user.id,
        )
    except Exception:
        logger.exception("Failed to acknowledge reminder %s", reminder_id_str)
        await callback.message.answer("Не удалось подтвердить напоминание.")
        return

    await callback.message.edit_reply_markup(reply_markup=None)
