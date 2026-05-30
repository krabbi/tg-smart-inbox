import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item
from bot.models.reminder import Reminder
from bot.repositories.item_repository import ItemRepository
from bot.repositories.reminder_repository import ReminderRepository


@dataclass(frozen=True)
class ReactivatedReminder:
    """Result of a successful reactivate_for_user call.

    ``item`` is ``None`` only in the defensive case where the parent Item row was
    deleted between the ownership check and the post-commit reload — the reminder
    itself was still reactivated and committed.
    """

    reminder: Reminder
    item: Item | None


class ReminderService:
    """Business logic for creating, querying, and acting on reminders."""

    def __init__(
        self,
        session: AsyncSession,
        repo: ReminderRepository,
        item_repo: ItemRepository,
    ) -> None:
        self._session = session
        self._repo = repo
        self._item_repo = item_repo

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
    ) -> ReactivatedReminder | None:
        """Reactivate an auto-completed reminder for ``user_id`` and load its Item.

        Returns ``None`` if the reminder is not owned by ``user_id`` or the row
        could not be reactivated. On success, returns the reactivated ``Reminder``
        bundled with its parent ``Item`` (which may be ``None`` only if the Item
        was deleted between the ownership check and the post-commit reload).
        """
        reminder = await self._repo.get_by_id_for_user(reminder_id, user_id)
        if reminder is None:
            return None
        updated = await self._repo.reactivate(reminder_id, remind_at)
        if updated is None:
            return None
        await self._session.commit()
        item = await self._item_repo.get_by_id(updated.item_id)
        return ReactivatedReminder(reminder=updated, item=item)
