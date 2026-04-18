import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Config
from bot.i18n import t
from bot.models.item import Item
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.repositories.reminder_repository import ReminderRepository
from bot.repositories.user_settings import UserSettingsRepository
from bot.services.embedding_service import EmbeddingService
from bot.services.reminder_service import ReminderService
from bot.services.user_settings_service import UserSettingsService
from bot.utils.datetime_utils import format_remind_at

logger = logging.getLogger(__name__)

_AUTO_RESEND_DELAY = timedelta(minutes=5)
_MAX_AUTO_RESENDS = 5
_REINDEX_BATCH_SIZE = 50
_REINDEX_INTERVAL_MINUTES = 10


def _snooze_keyboard(reminder_id: str, lang: str) -> InlineKeyboardMarkup:
    """Build the snooze/acknowledge keyboard for a reminder notification."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("reminder_btn_snooze_1h", lang),
                    callback_data=f"remind_snooze:1h:{reminder_id}",
                ),
                InlineKeyboardButton(
                    text=t("reminder_btn_snooze_1d", lang),
                    callback_data=f"remind_snooze:1d:{reminder_id}",
                ),
                InlineKeyboardButton(
                    text=t("reminder_btn_ack", lang),
                    callback_data=f"remind_ack:{reminder_id}",
                ),
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
                user_lang = await settings_svc.get_language(item.user_id)
                formatted = format_remind_at(reminder.remind_at, user_tz)
                await bot.send_message(
                    chat_id=item.user_id,
                    text=t(
                        "reminder_notification",
                        user_lang,
                        formatted=formatted,
                        content=item.content,
                    ),
                    reply_markup=_snooze_keyboard(str(reminder.id), user_lang),
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

                user_lang = await settings_svc.get_language(item.user_id)

                if reminder.snooze_count >= _MAX_AUTO_RESENDS:
                    # Too many auto-resends — notify the user that the reminder
                    # is being closed automatically, then acknowledge to stop spam.
                    await bot.send_message(
                        chat_id=item.user_id,
                        text=t(
                            "reminder_auto_closed",
                            user_lang,
                            content=item.content,
                        ),
                    )
                    await svc.mark_acknowledged(reminder)
                    continue

                new_reminder = await svc.prepare_auto_resend(original=reminder, remind_at=now)
                user_tz = await settings_svc.get_timezone(item.user_id)
                formatted = format_remind_at(new_reminder.remind_at, user_tz)
                await bot.send_message(
                    chat_id=item.user_id,
                    text=t(
                        "reminder_notification",
                        user_lang,
                        formatted=formatted,
                        content=item.content,
                    ),
                    reply_markup=_snooze_keyboard(str(new_reminder.id), user_lang),
                )
                await svc.mark_sent_with_auto_resend(new_reminder, now + _AUTO_RESEND_DELAY)
            except Exception:
                logger.exception("Failed to auto-resend reminder %s", reminder.id)


async def _reindex_missing_embeddings(
    session_factory: async_sessionmaker[AsyncSession],
    config: Config,
) -> None:
    """Populate embeddings for Items and Ideas that lack one. Runs in batches, skips failures."""
    embedding_service = EmbeddingService(config)
    async with session_factory() as session:
        item_repo = ItemRepository(session)
        idea_repo = IdeaRepository(session)

        items = await item_repo.get_missing_embedding(limit=_REINDEX_BATCH_SIZE)
        for item in items:
            try:
                vector = await embedding_service.generate_for_item(item)
                if vector is None:
                    continue
                await item_repo.update_embedding(item.id, vector)
                await session.commit()
            except Exception:
                logger.exception("Reindex failed for item %s", item.id)
                await session.rollback()

        idea_rows = await idea_repo.get_missing_embedding(limit=_REINDEX_BATCH_SIZE)
        for item, idea in idea_rows:
            try:
                idea.item = item
                vector = await embedding_service.generate_for_idea(idea)
                if vector is None:
                    continue
                await idea_repo.update_embedding(idea.id, vector)
                await session.commit()
            except Exception:
                logger.exception("Reindex failed for idea %s", idea.id)
                await session.rollback()


def start_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    config: Config | None = None,
) -> AsyncIOScheduler:
    """Create and start the APScheduler that fires reminders every 60 seconds.

    When ``config`` is provided, a background reindex job populates missing embeddings
    every ten minutes and once at startup.
    """
    scheduler = AsyncIOScheduler()
    reminder_kwargs = {"bot": bot, "session_factory": session_factory}
    scheduler.add_job(
        _send_due_reminders,
        trigger="interval",
        seconds=60,
        kwargs=reminder_kwargs,
    )
    scheduler.add_job(
        _auto_resend_reminders,
        trigger="interval",
        seconds=60,
        kwargs=reminder_kwargs,
    )
    if config is not None:
        scheduler.add_job(
            _reindex_missing_embeddings,
            trigger="interval",
            minutes=_REINDEX_INTERVAL_MINUTES,
            next_run_time=datetime.now(UTC),
            kwargs={"session_factory": session_factory, "config": config},
        )
    scheduler.start()
    return scheduler
