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

    async def cancel_for_user(self, reminder_id: uuid.UUID, user_id: int) -> bool:
        """Cancel a reminder only if it belongs to user_id; return False if not found/owned."""
        reminder = await self._repo.get_by_id_for_user(reminder_id, user_id)
        if reminder is None:
            return False
        await self._repo.cancel(reminder_id)
        await self._session.commit()
        return True

    async def get_upcoming(self, user_id: int) -> list[Reminder]:
        """Return upcoming (unsent, non-cancelled) reminders for a user."""
        return await self._repo.get_upcoming(user_id)

    async def mark_sent(self, reminder: Reminder) -> None:
        """Mark a reminder as sent and commit."""
        reminder.is_sent = True
        await self._session.commit()

    async def mark_sent_with_auto_resend(
        self, reminder: Reminder, auto_resend_at: datetime
    ) -> None:
        """Mark reminder as sent, set auto_resend_at window, and commit."""
        reminder.is_sent = True
        await self._repo.set_auto_resend_at(reminder, auto_resend_at)
        await self._session.commit()

    async def get_due_auto_resend(self, now: datetime) -> list[Reminder]:
        """Return reminders that need to be automatically re-sent."""
        return await self._repo.get_due_auto_resend(now)

    async def prepare_auto_resend(self, original: Reminder, remind_at: datetime) -> Reminder:
        """Acknowledge original and flush a new follow-up reminder; caller must commit."""
        await self._repo.acknowledge(original.id)
        new_reminder = await self._repo.create(item_id=original.item_id, remind_at=remind_at)
        new_reminder.snooze_count = original.snooze_count + 1
        await self._session.flush()
        return new_reminder

    async def mark_acknowledged(self, reminder: Reminder) -> None:
        """Acknowledge a reminder without user ownership check (for scheduler use)."""
        await self._repo.acknowledge(reminder.id)
        await self._session.commit()

    async def snooze(self, reminder_id: uuid.UUID, user_id: int, remind_at: datetime) -> bool:
        """Acknowledge original and create a snoozed reminder. Returns False if not owned."""
        reminder = await self._repo.get_by_id_for_user(reminder_id, user_id)
        if reminder is None:
            return False
        new_snooze_count = reminder.snooze_count + 1
        await self._repo.acknowledge(reminder_id)
        new_reminder = await self._repo.create(item_id=reminder.item_id, remind_at=remind_at)
        new_reminder.snooze_count = new_snooze_count
        await self._session.flush()
        await self._session.commit()
        return True

    async def acknowledge(self, reminder_id: uuid.UUID, user_id: int) -> bool:
        """Acknowledge a reminder. Returns False if not found or not owned by user."""
        reminder = await self._repo.get_by_id_for_user(reminder_id, user_id)
        if reminder is None:
            return False
        await self._repo.acknowledge(reminder_id)
        await self._session.commit()
        return True
