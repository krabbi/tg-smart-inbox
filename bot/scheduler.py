import asyncio
import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Config
from bot.handlers.reminders import build_snooze_keyboard
from bot.i18n import t
from bot.models.item import Item
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.repositories.reminder_repository import ReminderRepository
from bot.repositories.user_settings import UserSettingsRepository
from bot.services.embedding_service import EmbeddingService
from bot.services.reindex_service import ReindexService
from bot.services.reminder_service import ReminderService
from bot.services.user_settings_service import UserSettingsService
from bot.utils.datetime_utils import format_remind_at
from bot.utils.text import format_item_display

logger = logging.getLogger(__name__)

_AUTO_ARCHIVE_DELAY = timedelta(hours=24)
_REINDEX_BATCH_SIZE = 50
_REINDEX_INTERVAL_MINUTES = 10
_REINDEX_THROTTLE_SECONDS = 22.0  # Voyage AI free tier: 3 RPM → ≥20s between requests


def _reactivate_keyboard(reminder_id: str, lang: str) -> InlineKeyboardMarkup:
    """Build the single-button keyboard for an auto-archived reminder notification."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("reminder_btn_reactivate", lang),
                    callback_data=f"remind_reactivate:{reminder_id}",
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
        svc = ReminderService(session, repo, ItemRepository(session))
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
                        content=format_item_display(item),
                    ),
                    reply_markup=build_snooze_keyboard(str(reminder.id), user_lang),
                )
                await svc.mark_sent_with_auto_archive(reminder, now + _AUTO_ARCHIVE_DELAY)
            except Exception:
                logger.exception("Failed to send reminder %s", reminder.id)


async def _auto_archive_reminders(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Mark reminders without user action after 24h as auto-completed and notify the user."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        repo = ReminderRepository(session)
        svc = ReminderService(session, repo, ItemRepository(session))
        settings_svc = UserSettingsService(session, UserSettingsRepository(session))
        due = await svc.get_due_auto_archive(now)
        for reminder in due:
            try:
                item: Item = await session.get(Item, reminder.item_id)  # type: ignore[assignment]
                if item is None:
                    # The parent Item is gone — just close the reminder silently.
                    await svc.mark_auto_completed(reminder)
                    continue

                user_lang = await settings_svc.get_language(item.user_id)
                await bot.send_message(
                    chat_id=item.user_id,
                    text=t(
                        "reminder_auto_completed",
                        user_lang,
                        content=format_item_display(item),
                    ),
                    reply_markup=_reactivate_keyboard(str(reminder.id), user_lang),
                )
                await svc.mark_auto_completed(reminder)
            except Exception:
                logger.exception("Failed to auto-archive reminder %s", reminder.id)


async def _reindex_missing_embeddings(
    session_factory: async_sessionmaker[AsyncSession],
    config: Config,
) -> None:
    """Populate embeddings for Items and Ideas that lack one. Runs in batches, skips failures."""
    if not ReindexService.try_start_scheduler_reindex():
        logger.info("Skipping scheduler reindex because another reindex run is active")
        return

    try:
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
                    # Voyage AI free tier allows 3 RPM; keep scheduler safely below it.
                    await asyncio.sleep(_REINDEX_THROTTLE_SECONDS)
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
                    # Voyage AI free tier allows 3 RPM; keep scheduler safely below it.
                    await asyncio.sleep(_REINDEX_THROTTLE_SECONDS)
                except Exception:
                    logger.exception("Reindex failed for idea %s", idea.id)
                    await session.rollback()
    finally:
        ReindexService.finish_scheduler_reindex()


def start_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    config: Config | None = None,
) -> AsyncIOScheduler:
    """Create and start the APScheduler that fires reminders every 60 seconds.

    When ``config`` is provided, a background reindex job populates missing embeddings
    every ten minutes.
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
        _auto_archive_reminders,
        trigger="interval",
        seconds=60,
        kwargs=reminder_kwargs,
    )
    if config is not None:
        scheduler.add_job(
            _reindex_missing_embeddings,
            trigger="interval",
            minutes=_REINDEX_INTERVAL_MINUTES,
            kwargs={"session_factory": session_factory, "config": config},
        )
    scheduler.start()
    return scheduler
