import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.reminder import Reminder


class ReminderRepository:
    """CRUD access for Reminder records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, item_id: uuid.UUID, remind_at: datetime) -> Reminder:
        """Create and flush a new Reminder; caller is responsible for commit."""
        reminder = Reminder(item_id=item_id, remind_at=remind_at)
        self._session.add(reminder)
        await self._session.flush()
        await self._session.refresh(reminder)
        return reminder

    async def get_due(self, now: datetime) -> list[Reminder]:
        """Return all unsent, non-cancelled reminders with remind_at <= now."""
        result = await self._session.execute(
            select(Reminder).where(
                Reminder.remind_at <= now,
                Reminder.is_sent.is_(False),
                Reminder.is_cancelled.is_(False),
            )
        )
        return list(result.scalars().all())

    async def get_by_user_pending(self, user_id: int) -> list[Reminder]:
        """Return unsent, non-cancelled reminders for a user via Item join."""
        from bot.models.item import Item

        result = await self._session.execute(
            select(Reminder)
            .join(Item, Reminder.item_id == Item.id)
            .where(
                Item.user_id == user_id,
                Reminder.is_sent.is_(False),
                Reminder.is_cancelled.is_(False),
            )
            .order_by(Reminder.remind_at.asc())
        )
        return list(result.scalars().all())

    async def cancel(self, reminder_id: uuid.UUID) -> None:
        """Mark a reminder as cancelled."""
        result = await self._session.execute(
            select(Reminder).where(Reminder.id == reminder_id)
        )
        reminder = result.scalar_one_or_none()
        if reminder:
            reminder.is_cancelled = True
            await self._session.flush()
