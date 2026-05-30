import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.reminder import Reminder
from bot.repositories.reminder_repository import ReminderRepository


class ReminderService:
    """Business logic for creating, querying, and acting on reminders."""

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

    async def mark_sent_with_auto_archive(
        self, reminder: Reminder, auto_archive_at: datetime
    ) -> None:
        """Mark reminder as sent, set auto_archive_at window, and commit."""
        reminder.is_sent = True
        await self._repo.set_auto_archive_at(reminder, auto_archive_at)
        await self._session.commit()

    async def get_due_auto_archive(self, now: datetime) -> list[Reminder]:
        """Return reminders whose 24h auto-archive window has elapsed without user action."""
        return await self._repo.get_due_auto_archive(now)

    async def mark_auto_completed(self, reminder: Reminder) -> None:
        """Flag a reminder as auto-completed and commit (used by scheduler)."""
        await self._repo.mark_auto_completed(reminder.id)
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

    async def reactivate_for_user(
        self, reminder_id: uuid.UUID, user_id: int, remind_at: datetime
    ) -> Reminder | None:
        """Reactivate an auto-completed reminder for ``user_id``; return the row or None."""
        reminder = await self._repo.get_by_id_for_user(reminder_id, user_id)
        if reminder is None:
            return None
        updated = await self._repo.reactivate(reminder_id, remind_at)
        if updated is None:
            return None
        await self._session.commit()
        return updated
