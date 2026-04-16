import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.models.item import Item
from bot.repositories.reminder_repository import ReminderRepository
from bot.repositories.user_settings import UserSettingsRepository
from bot.services.reminder_service import ReminderService
from bot.services.user_settings_service import UserSettingsService
from bot.utils.datetime_utils import format_remind_at

logger = logging.getLogger(__name__)

_AUTO_RESEND_DELAY = timedelta(minutes=5)
_MAX_AUTO_RESENDS = 5


def _snooze_keyboard(reminder_id: str) -> InlineKeyboardMarkup:
    """Build the snooze/acknowledge keyboard for a reminder notification."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏰ +1ч", callback_data=f"remind_snooze:1h:{reminder_id}"
                ),
                InlineKeyboardButton(
                    text="🌙 +1д", callback_data=f"remind_snooze:1d:{reminder_id}"
                ),
                InlineKeyboardButton(text="✅ Принято", callback_data=f"remind_ack:{reminder_id}"),
            ]
        ]
    )


async def _send_due_reminders(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Check for due reminders and send notifications with snooze/ack keyboard."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        repo = ReminderRepository(session)
        svc = ReminderService(session, repo)
        settings_svc = UserSettingsService(session, UserSettingsRepository(session))
        due = await svc.get_due(now)
        for reminder in due:
            try:
                item: Item = await session.get(Item, reminder.item_id)  # type: ignore[assignment]
                if item is None:
                    await svc.mark_sent(reminder)
                    continue
                user_tz = await settings_svc.get_timezone(item.user_id)
                formatted = format_remind_at(reminder.remind_at, user_tz)
                await bot.send_message(
                    chat_id=item.user_id,
                    text=f"🔔 Напомню {formatted}\n{item.content}",
                    reply_markup=_snooze_keyboard(str(reminder.id)),
                )
                await svc.mark_sent_with_auto_resend(reminder, now + _AUTO_RESEND_DELAY)
            except Exception:
                logger.exception("Failed to send reminder %s", reminder.id)


async def _auto_resend_reminders(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Re-send reminders that were not acknowledged within the auto-resend window."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        repo = ReminderRepository(session)
        svc = ReminderService(session, repo)
        settings_svc = UserSettingsService(session, UserSettingsRepository(session))
        due = await svc.get_due_auto_resend(now)
        for reminder in due:
            try:
                item: Item = await session.get(Item, reminder.item_id)  # type: ignore[assignment]
                if item is None:
                    await svc.mark_acknowledged(reminder)
                    continue

                if reminder.snooze_count >= _MAX_AUTO_RESENDS:
                    # Too many auto-resends — notify the user that the reminder
                    # is being closed automatically, then acknowledge to stop spam.
                    await bot.send_message(
                        chat_id=item.user_id,
                        text=f"🔔 Напоминание закрыто автоматически: {item.content}",
                    )
                    await svc.mark_acknowledged(reminder)
                    continue

                new_reminder = await svc.prepare_auto_resend(original=reminder, remind_at=now)
                user_tz = await settings_svc.get_timezone(item.user_id)
                formatted = format_remind_at(new_reminder.remind_at, user_tz)
                await bot.send_message(
                    chat_id=item.user_id,
                    text=f"🔔 Напомню {formatted}\n{item.content}",
                    reply_markup=_snooze_keyboard(str(new_reminder.id)),
                )
                await svc.mark_sent_with_auto_resend(new_reminder, now + _AUTO_RESEND_DELAY)
            except Exception:
                logger.exception("Failed to auto-resend reminder %s", reminder.id)


def start_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIOScheduler:
    """Create and start the APScheduler that fires reminders every 60 seconds."""
    scheduler = AsyncIOScheduler()
    kwargs = {"bot": bot, "session_factory": session_factory}
    scheduler.add_job(
        _send_due_reminders,
        trigger="interval",
        seconds=60,
        kwargs=kwargs,
    )
    scheduler.add_job(
        _auto_resend_reminders,
        trigger="interval",
        seconds=60,
        kwargs=kwargs,
    )
    scheduler.start()
    return scheduler
