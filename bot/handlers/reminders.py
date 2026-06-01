import logging
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from bot.i18n import t
from bot.services.link_service import LinkService
from bot.services.reminder_service import ReminderService
from bot.services.time_parser import TimeParser
from bot.services.user_settings_service import UserSettingsService
from bot.utils.datetime_utils import format_remind_at
from bot.utils.text import extract_url, format_item_display

# 24h window between sending a reminder and auto-archiving it if the user
# hasn't pressed any of the snooze / ack / reactivate buttons. Mirrors the
# constant used by the scheduler — kept in sync intentionally.
_AUTO_ARCHIVE_DELAY = timedelta(hours=24)

logger = logging.getLogger(__name__)

router = Router(name="reminders")


class ReminderStates(StatesGroup):
    waiting_for_time = State()


_ITEM_ID_KEY = "reminder_item_id"
_TASK_TEXT_KEY = "reminder_task_text"
_ATTEMPTS_KEY = "reminder_attempts"
_MAX_ATTEMPTS = 3


def task_remind_keyboard(item_id: str, lang: str) -> InlineKeyboardMarkup:
    """Build inline keyboard with a single 'Remind' button carrying item_id."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("task_btn_remind", lang),
                    callback_data=f"task_remind:{item_id}",
                ),
            ]
        ]
    )


def build_snooze_keyboard(reminder_id: str, lang: str) -> InlineKeyboardMarkup:
    """Build the 4-button snooze/acknowledge keyboard for an active reminder notification."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("reminder_btn_snooze_1h", lang),
                    callback_data=f"remind_snooze:1h:{reminder_id}",
                ),
                InlineKeyboardButton(
                    text=t("reminder_btn_snooze_24h", lang),
                    callback_data=f"remind_snooze:24h:{reminder_id}",
                ),
                InlineKeyboardButton(
                    text=t("reminder_btn_snooze_tomorrow", lang),
                    callback_data=f"remind_snooze:tomorrow:{reminder_id}",
                ),
                InlineKeyboardButton(
                    text=t("reminder_btn_ack", lang),
                    callback_data=f"remind_ack:{reminder_id}",
                ),
            ]
        ]
    )


# Keep the old name as an alias so scheduler.py and other callers can import it.
_snooze_keyboard = build_snooze_keyboard


def _next_day_same_time(remind_at: datetime, user_tz: str) -> datetime:
    """Return a datetime exactly one calendar day after ``remind_at`` at the same wall-clock time.

    The calculation is DST-safe: we localise ``remind_at`` to ``user_tz``, add one day to
    the date component while preserving the hour/minute, then convert back to UTC.
    Falls back to a simple 24-hour offset if the timezone string is invalid.
    """
    try:
        tz = ZoneInfo(user_tz)
    except (ZoneInfoNotFoundError, KeyError):
        # Unknown timezone — fall back to a plain 24h offset.
        return remind_at + timedelta(days=1)

    # Convert to local time.
    local = remind_at.astimezone(tz)
    # Move one calendar day forward keeping the same local hour/minute/second.
    next_local = local.replace(day=local.day) + timedelta(days=1)
    # Re-express with the same wall-clock time; fold=0 selects the first occurrence
    # on ambiguous DST transitions (i.e. "the earlier" of the two possible instants).
    next_local = local.replace(
        year=next_local.year,
        month=next_local.month,
        day=next_local.day,
        fold=0,
    )
    return next_local.astimezone(UTC)


@router.callback_query(F.data.startswith("task_remind:"))
async def cb_task_remind(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    """Handle 'Remind' button on a saved task — enter time input FSM."""
    await callback.answer()
    if callback.message is None:
        return

    item_id = (callback.data or "").removeprefix("task_remind:")

    await callback.message.edit_reply_markup(reply_markup=None)

    await state.update_data({_ITEM_ID_KEY: item_id, _ATTEMPTS_KEY: 0})
    await state.set_state(ReminderStates.waiting_for_time)
    await callback.message.answer(t("reminder_prompt_when", lang))


@router.message(ReminderStates.waiting_for_time)
async def receive_reminder_time(
    message: Message,
    state: FSMContext,
    time_parser: TimeParser | None = None,
    reminder_service: ReminderService | None = None,
    link_service: LinkService | None = None,
    user_settings_service: UserSettingsService | None = None,
    lang: str = "en",
) -> None:
    """Parse the user's time expression and create the reminder."""
    # Local import avoids the reminders ↔ links circular import at module level.
    from bot.handlers.links import handle_link_message

    # A URL while waiting for time means the user switched tasks mid-dialog —
    # exit the FSM and route the link through the normal link flow instead of
    # feeding it to the time parser (which would always fail).
    url = extract_url(message.text or "")
    if url is not None:
        await state.clear()
        if link_service is None:
            await message.answer(t("link_service_unavailable", lang))
            return
        await handle_link_message(message, url, link_service, lang)
        return

    if time_parser is None or reminder_service is None:
        await message.answer(t("reminder_service_unavailable", lang))
        await state.clear()
        return

    data = await state.get_data()
    item_id_str = data.get(_ITEM_ID_KEY, "")

    user_id = message.from_user.id if message.from_user else 0
    user_tz = "UTC"
    if user_settings_service is not None and user_id:
        user_tz = await user_settings_service.get_timezone(user_id)

    try:
        remind_at = await time_parser.parse(
            message.text or "", now=datetime.now(UTC), user_tz=user_tz
        )
    except TimeParseError:
        data = await state.get_data()
        attempts = data.get(_ATTEMPTS_KEY, 0) + 1
        if attempts >= _MAX_ATTEMPTS:
            await state.clear()
            await message.answer(t("reminder_time_parse_failed_final", lang))
            return
        await state.update_data({_ATTEMPTS_KEY: attempts})
        await message.answer(
            t(
                "reminder_time_parse_retry",
                lang,
                attempts=attempts,
                max_attempts=_MAX_ATTEMPTS,
            )
        )
        return

    try:
        item_id = uuid.UUID(item_id_str)
        await reminder_service.create(item_id=item_id, remind_at=remind_at)
    except Exception:
        logger.exception("Failed to save reminder for item %s", item_id_str)
        await message.answer(t("reminder_save_failed", lang))
        await state.clear()
        return

    await state.clear()
    formatted = format_remind_at(remind_at, user_tz)
    await message.answer(t("reminder_created", lang, formatted=formatted))


@router.callback_query(F.data.startswith("remind_snooze:"))
async def cb_remind_snooze(
    callback: CallbackQuery,
    reminder_service: ReminderService | None = None,
    user_settings_service: UserSettingsService | None = None,
    lang: str = "en",
) -> None:
    """Snooze a reminder by 1 hour, 24 hours, or until tomorrow at the same time."""
    await callback.answer()
    if callback.message is None or callback.from_user is None:
        return

    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        return

    _, period, reminder_id_str = parts

    if reminder_service is None:
        await callback.message.answer(t("reminder_service_unavailable", lang))
        return

    user_tz = "UTC"
    if user_settings_service is not None:
        user_tz = await user_settings_service.get_timezone(callback.from_user.id)

    try:
        reminder_id = uuid.UUID(reminder_id_str)

        if period == "tomorrow":
            # Read the current remind_at from the DB so Tomorrow uses the last
            # snoozed time, not the moment the button is pressed.
            existing = await reminder_service.get_by_id_for_user(reminder_id, callback.from_user.id)
            if existing is None:
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.answer(t("reminder_not_found_or_inactive", lang))
                return
            remind_at = _next_day_same_time(existing.remind_at, user_tz)
            is_tomorrow = True
        else:
            # Both "24h" and legacy "1d" map to 24 hours from now.
            delta = timedelta(hours=1) if period == "1h" else timedelta(hours=24)
            remind_at = datetime.now(UTC) + delta
            is_tomorrow = False

        ok = await reminder_service.snooze(
            reminder_id=reminder_id,
            user_id=callback.from_user.id,
            remind_at=remind_at,
        )
    except Exception:
        logger.exception("Failed to snooze reminder %s", reminder_id_str)
        await callback.message.answer(t("reminder_snooze_failed", lang))
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    if ok:
        formatted = format_remind_at(remind_at, user_tz)
        if is_tomorrow:
            await callback.message.answer(t("reminder_snoozed_tomorrow", lang, formatted=formatted))
        else:
            label = (
                t("reminder_snooze_1h_label", lang)
                if period == "1h"
                else t("reminder_snooze_24h_label", lang)
            )
            await callback.message.answer(
                t("reminder_snoozed", lang, period=label, formatted=formatted)
            )
    else:
        await callback.message.answer(t("reminder_not_found_or_inactive", lang))


@router.callback_query(F.data.startswith("remind_ack:"))
async def cb_remind_ack(
    callback: CallbackQuery,
    reminder_service: ReminderService | None = None,
    lang: str = "en",
) -> None:
    """Acknowledge a reminder — user has seen and processed it."""
    await callback.answer()
    if callback.message is None or callback.from_user is None:
        return

    reminder_id_str = (callback.data or "").removeprefix("remind_ack:")

    if reminder_service is None:
        await callback.message.answer(t("reminder_service_unavailable", lang))
        return

    try:
        reminder_id = uuid.UUID(reminder_id_str)
        await reminder_service.acknowledge(
            reminder_id=reminder_id,
            user_id=callback.from_user.id,
        )
    except Exception:
        logger.exception("Failed to acknowledge reminder %s", reminder_id_str)
        await callback.message.answer(t("reminder_ack_failed", lang))
        return

    existing_text = callback.message.html_text or callback.message.text or ""
    await callback.message.edit_text(
        existing_text + f"\n\n{t('reminder_ack_done', lang)}",
        parse_mode="HTML",
        reply_markup=None,
    )


@router.callback_query(F.data.startswith("remind_reactivate:"))
async def cb_remind_reactivate(
    callback: CallbackQuery,
    reminder_service: ReminderService | None = None,
    user_settings_service: UserSettingsService | None = None,
    lang: str = "en",
) -> None:
    """Reactivate an auto-completed reminder and immediately re-send the notification."""
    await callback.answer()
    if callback.message is None or callback.from_user is None:
        return

    if reminder_service is None:
        await callback.message.answer(t("reminder_service_unavailable", lang))
        return

    reminder_id_str = (callback.data or "").removeprefix("remind_reactivate:")

    try:
        reminder_id = uuid.UUID(reminder_id_str)
    except ValueError:
        await callback.message.answer(t("reminder_not_found_or_inactive", lang))
        return

    now = datetime.now(UTC)
    try:
        result = await reminder_service.reactivate_for_user(
            reminder_id=reminder_id,
            user_id=callback.from_user.id,
            remind_at=now,
        )
    except Exception:
        logger.exception("Failed to reactivate reminder %s", reminder_id_str)
        await callback.message.answer(t("reminder_reactivate_failed", lang))
        return

    if result is None:
        await callback.message.answer(t("reminder_not_found_or_inactive", lang))
        return

    reminder = result.reminder
    item = result.item
    if item is None:
        # Defensive: the parent record was deleted between reactivate and re-send.
        # The service has still committed the reactivation, but there is nothing to display.
        await callback.message.answer(t("reminder_reactivate_failed", lang))
        return

    # Reactivated reminders are pushed to the user right away and immediately
    # enter the 24h auto-archive window again, exactly like a fresh due notice.
    user_tz = "UTC"
    if user_settings_service is not None:
        user_tz = await user_settings_service.get_timezone(callback.from_user.id)
    formatted = format_remind_at(reminder.remind_at, user_tz)

    # Strip the "Реактивировать" button on the old auto-archive notice so the
    # user can't click it twice, then signal that the row is back to active.
    existing_text = callback.message.html_text or callback.message.text or ""
    try:
        await callback.message.edit_text(
            existing_text + f"\n\n{t('reminder_reactivated_marker', lang)}",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        # Telegram may reject edits to messages older than 48h — fall through to
        # send the fresh notification regardless.
        logger.warning("Could not edit auto-archive message for reminder %s", reminder_id_str)

    await callback.message.answer(
        t(
            "reminder_notification",
            lang,
            formatted=formatted,
            content=format_item_display(item),
        ),
        reply_markup=_snooze_keyboard(str(reminder.id), lang),
    )
    await reminder_service.mark_sent_with_auto_archive(reminder, now + _AUTO_ARCHIVE_DELAY)
