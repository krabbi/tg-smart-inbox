import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.reminder import Reminder
from bot.repositories.reminder_repository import ReminderRepository


class ReminderService:
    """Business logic for creating, querying, and cancelling reminders."""

    def __init__(self, session: AsyncSession, repo: ReminderRepository) -> None:
        self._session = session
        self._repo = repo

    async def create(self, item_id: uuid.UUID, remind_at: datetime) -> Reminder:
        """Save a new reminder and commit the transaction."""
        reminder = await self._repo.create(item_id=item_id, remind_at=remind_at)
        await self._session.commit()
        return reminder

    async def get_due(self, now: datetime) -> list[Reminder]:
        """Return all reminders due at or before now."""
        return await self._repo.get_due(now)

    async def cancel(self, reminder_id: uuid.UUID) -> None:
        """Cancel a reminder and commit."""
        await self._repo.cancel(reminder_id)
        await self._session.commit()

    async def mark_sent(self, reminder: Reminder) -> None:
        """Mark a reminder as sent and commit."""
        reminder.is_sent = True
        await self._session.commit()
