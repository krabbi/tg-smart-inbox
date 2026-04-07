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

    async def get_upcoming(self, user_id: int) -> list[Reminder]:
        """Return unsent, non-cancelled reminders for a user, soonest first."""
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

    async def get_by_id_for_user(self, reminder_id: uuid.UUID, user_id: int) -> Reminder | None:
        """Return a reminder only if it belongs to user_id; None otherwise."""
        from bot.models.item import Item

        result = await self._session.execute(
            select(Reminder)
            .join(Item, Reminder.item_id == Item.id)
            .where(Reminder.id == reminder_id, Item.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def cancel(self, reminder_id: uuid.UUID) -> None:
        """Mark a reminder as cancelled."""
        result = await self._session.execute(select(Reminder).where(Reminder.id == reminder_id))
        reminder = result.scalar_one_or_none()
        if reminder:
            reminder.is_cancelled = True
            await self._session.flush()

    async def set_auto_resend_at(self, reminder: Reminder, auto_resend_at: datetime) -> None:
        """Set auto_resend_at on a reminder and flush."""
        reminder.auto_resend_at = auto_resend_at
        await self._session.flush()

    async def get_due_auto_resend(self, now: datetime) -> list[Reminder]:
        """Return sent, unacknowledged reminders whose auto_resend_at has passed."""
        result = await self._session.execute(
            select(Reminder).where(
                Reminder.is_sent.is_(True),
                Reminder.is_acknowledged.is_(False),
                Reminder.is_cancelled.is_(False),
                Reminder.auto_resend_at.is_not(None),
                Reminder.auto_resend_at <= now,
            )
        )
        return list(result.scalars().all())

    async def acknowledge(self, reminder_id: uuid.UUID) -> None:
        """Mark a reminder as acknowledged and clear auto_resend_at."""
        result = await self._session.execute(select(Reminder).where(Reminder.id == reminder_id))
        reminder = result.scalar_one_or_none()
        if reminder:
            reminder.is_acknowledged = True
            reminder.auto_resend_at = None
            await self._session.flush()
