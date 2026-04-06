import logging
from datetime import UTC, datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.models.item import Item
from bot.repositories.reminder_repository import ReminderRepository
from bot.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)


async def _send_due_reminders(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Check for due reminders and send notifications."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        repo = ReminderRepository(session)
        svc = ReminderService(session, repo)
        due = await svc.get_due(now)
        for reminder in due:
            try:
                item: Item = await session.get(Item, reminder.item_id)  # type: ignore[assignment]
                if item is None:
                    await svc.mark_sent(reminder)
                    continue
                await bot.send_message(
                    chat_id=item.user_id,
                    text=f"🔔 Напоминание:\n{item.content}",
                )
                await svc.mark_sent(reminder)
            except Exception:
                logger.exception("Failed to send reminder %s", reminder.id)


def start_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIOScheduler:
    """Create and start the APScheduler that fires reminders every 60 seconds."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _send_due_reminders,
        trigger="interval",
        seconds=60,
        kwargs={"bot": bot, "session_factory": session_factory},
    )
    scheduler.start()
    return scheduler
