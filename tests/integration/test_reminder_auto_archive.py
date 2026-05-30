"""End-to-end integration coverage for the 24h auto-archive / reactivate lifecycle."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.reminder_repository import ReminderRepository
from bot.services.reminder_service import ReminderService


async def test_reminder_lifecycle_send_then_auto_archive_then_reactivate(
    db_session: AsyncSession,
) -> None:
    """A reminder marked for auto-archive can be reactivated and sent again."""
    item = Item(user_id=1, type=ItemType.task, content="buy milk")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    svc = ReminderService(db_session, repo)

    # 1. Create a reminder due in the past — eligible for the next send tick.
    past = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    reminder = await svc.create(item_id=item.id, remind_at=past)

    # 2. Scheduler delivers it and arms the 24h auto-archive timer.
    sent_at = datetime(2026, 5, 1, 10, 1, tzinfo=UTC)
    await svc.mark_sent_with_auto_archive(reminder, sent_at + timedelta(hours=24))
    await db_session.refresh(reminder)
    assert reminder.is_sent is True
    assert reminder.auto_archive_at is not None

    # 3. 24h later, the auto-archive job picks the reminder up.
    later = sent_at + timedelta(hours=25)
    due = await svc.get_due_auto_archive(later)
    assert any(r.id == reminder.id for r in due)

    # 4. The auto-archive job marks it completed and clears the timer.
    await svc.mark_auto_completed(reminder)
    await db_session.refresh(reminder)
    assert reminder.is_auto_completed is True
    assert reminder.auto_archive_at is None

    # 5. After mark, the reminder no longer appears in the auto-archive queue
    #    even though its timer column was non-null when the job ran.
    due_after = await svc.get_due_auto_archive(later + timedelta(hours=1))
    assert all(r.id != reminder.id for r in due_after)

    # 6. User clicks "Реактивировать" — service resets state and gives a new remind_at.
    reactivate_at = sent_at + timedelta(hours=26)
    reactivated = await svc.reactivate_for_user(
        reminder_id=reminder.id, user_id=1, remind_at=reactivate_at
    )
    assert reactivated is not None
    await db_session.refresh(reminder)
    assert reminder.is_auto_completed is False
    assert reminder.is_sent is False
    assert reminder.auto_archive_at is None
    assert reminder.remind_at.replace(tzinfo=None) == reactivate_at.replace(tzinfo=None)

    # 7. The reactivated reminder is again eligible for the regular due query.
    due_again = await svc.get_due(reactivate_at + timedelta(seconds=1))
    assert any(r.id == reminder.id for r in due_again)


async def test_acknowledge_before_24h_prevents_auto_archive(db_session: AsyncSession) -> None:
    """User ack inside the 24h window clears auto_archive_at — job ignores the row."""
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    svc = ReminderService(db_session, repo)

    past = datetime(2026, 5, 1, tzinfo=UTC)
    reminder = await svc.create(item_id=item.id, remind_at=past)
    sent_at = past + timedelta(minutes=1)
    await svc.mark_sent_with_auto_archive(reminder, sent_at + timedelta(hours=24))

    # User acknowledges 10 minutes after send — well within the 24h window.
    assert await svc.acknowledge(reminder_id=reminder.id, user_id=1) is True
    await db_session.refresh(reminder)
    assert reminder.is_acknowledged is True
    assert reminder.auto_archive_at is None

    # 30h later, the auto-archive job sees an empty queue.
    due = await svc.get_due_auto_archive(sent_at + timedelta(hours=30))
    assert all(r.id != reminder.id for r in due)


async def test_snooze_before_24h_prevents_auto_archive_on_original(
    db_session: AsyncSession,
) -> None:
    """Snoozing clears auto_archive_at on the original — only the snoozed copy is active."""
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    svc = ReminderService(db_session, repo)

    past = datetime(2026, 5, 1, tzinfo=UTC)
    reminder = await svc.create(item_id=item.id, remind_at=past)
    sent_at = past + timedelta(minutes=1)
    await svc.mark_sent_with_auto_archive(reminder, sent_at + timedelta(hours=24))

    snooze_at = past + timedelta(hours=1)
    assert await svc.snooze(reminder_id=reminder.id, user_id=1, remind_at=snooze_at) is True
    await db_session.refresh(reminder)
    # The original row is now acknowledged with timer cleared. A separate fresh
    # row carries the snoozed remind_at.
    assert reminder.is_acknowledged is True
    assert reminder.auto_archive_at is None

    due = await svc.get_due_auto_archive(sent_at + timedelta(hours=30))
    assert all(r.id != reminder.id for r in due)


async def test_cancel_clears_auto_archive_timer(db_session: AsyncSession) -> None:
    """Cancelling a sent reminder also clears its auto-archive timer."""
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    svc = ReminderService(db_session, repo)

    past = datetime(2026, 5, 1, tzinfo=UTC)
    reminder = await svc.create(item_id=item.id, remind_at=past)
    await svc.mark_sent_with_auto_archive(reminder, past + timedelta(hours=24))

    assert await svc.cancel_for_user(reminder_id=reminder.id, user_id=1) is True
    await db_session.refresh(reminder)
    assert reminder.is_cancelled is True
    assert reminder.auto_archive_at is None


async def test_reactivate_rejects_foreign_user(db_session: AsyncSession) -> None:
    """A user cannot reactivate another user's reminder."""
    owner_item = Item(user_id=1, type=ItemType.task, content="mine")
    other_item = Item(user_id=2, type=ItemType.task, content="theirs")
    db_session.add_all([owner_item, other_item])
    await db_session.flush()

    repo = ReminderRepository(db_session)
    svc = ReminderService(db_session, repo)

    reminder = await svc.create(item_id=owner_item.id, remind_at=datetime(2026, 5, 1, tzinfo=UTC))
    await svc.mark_auto_completed(reminder)

    # User 2 tries to reactivate user 1's reminder — must be denied.
    result = await svc.reactivate_for_user(
        reminder_id=reminder.id,
        user_id=2,
        remind_at=datetime(2026, 5, 2, tzinfo=UTC),
    )
    assert result is None

    await db_session.refresh(reminder)
    assert reminder.is_auto_completed is True
