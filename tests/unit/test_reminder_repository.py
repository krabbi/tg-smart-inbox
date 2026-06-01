import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.models.reminder import Reminder
from bot.repositories.reminder_repository import ReminderRepository


async def test_create_returns_reminder(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="buy milk")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    remind_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    reminder = await repo.create(item_id=item.id, remind_at=remind_at)
    await db_session.commit()

    assert isinstance(reminder, Reminder)
    assert reminder.item_id == item.id
    assert reminder.is_sent is False
    assert reminder.is_cancelled is False
    assert reminder.is_auto_completed is False


async def test_get_due_returns_past_due(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    past = datetime(2026, 5, 1, tzinfo=UTC)
    future = datetime(2026, 12, 1, tzinfo=UTC)
    await repo.create(item_id=item.id, remind_at=past)
    await repo.create(item_id=item.id, remind_at=future)
    await db_session.commit()

    now = datetime(2026, 6, 1, tzinfo=UTC)
    due = await repo.get_due(now)
    assert len(due) == 1
    # SQLite strips tzinfo when reading back; compare naive datetimes
    assert due[0].remind_at.replace(tzinfo=None) == past.replace(tzinfo=None)


async def test_get_due_excludes_sent(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    past = datetime(2026, 5, 1, tzinfo=UTC)
    r = await repo.create(item_id=item.id, remind_at=past)
    r.is_sent = True
    await db_session.commit()

    now = datetime(2026, 6, 1, tzinfo=UTC)
    due = await repo.get_due(now)
    assert len(due) == 0


async def test_get_due_excludes_cancelled(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    past = datetime(2026, 5, 1, tzinfo=UTC)
    r = await repo.create(item_id=item.id, remind_at=past)
    r.is_cancelled = True
    await db_session.commit()

    now = datetime(2026, 6, 1, tzinfo=UTC)
    due = await repo.get_due(now)
    assert len(due) == 0


async def test_cancel_sets_flag_and_clears_archive_timer(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    r.auto_archive_at = datetime(2026, 6, 2, tzinfo=UTC)
    await db_session.commit()

    await repo.cancel(r.id)
    await db_session.commit()
    await db_session.refresh(r)

    assert r.is_cancelled is True
    assert r.auto_archive_at is None


async def test_cancel_nonexistent_id_does_nothing(db_session: AsyncSession) -> None:
    repo = ReminderRepository(db_session)
    await repo.cancel(uuid.uuid4())  # should not raise


async def test_get_upcoming(db_session: AsyncSession) -> None:
    item1 = Item(user_id=10, type=ItemType.task, content="task user 10")
    item2 = Item(user_id=20, type=ItemType.task, content="task user 20")
    db_session.add_all([item1, item2])
    await db_session.flush()

    repo = ReminderRepository(db_session)
    await repo.create(item_id=item1.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    await repo.create(item_id=item2.id, remind_at=datetime(2026, 6, 2, tzinfo=UTC))
    await db_session.commit()

    results = await repo.get_upcoming(10)
    assert len(results) == 1
    assert results[0].item_id == item1.id


async def test_get_by_id_for_user_returns_owned(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="my task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    reminder = await repo.create(item_id=item.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    await db_session.commit()

    found = await repo.get_by_id_for_user(reminder.id, user_id=1)
    assert found is not None
    assert found.id == reminder.id


async def test_get_by_id_for_user_returns_none_for_wrong_user(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="my task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    reminder = await repo.create(item_id=item.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    await db_session.commit()

    found = await repo.get_by_id_for_user(reminder.id, user_id=999)
    assert found is None


async def test_acknowledge_sets_flag_and_clears_archive_timer(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    r.auto_archive_at = datetime(2026, 6, 2, 10, 5, tzinfo=UTC)
    await db_session.commit()

    await repo.acknowledge(r.id)
    await db_session.commit()
    await db_session.refresh(r)

    assert r.is_acknowledged is True
    assert r.auto_archive_at is None


async def test_get_due_auto_archive_returns_overdue(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 5, 1, tzinfo=UTC))
    r.is_sent = True
    r.auto_archive_at = datetime(2026, 5, 2, tzinfo=UTC)
    await db_session.commit()

    now = datetime(2026, 6, 1, tzinfo=UTC)
    due = await repo.get_due_auto_archive(now)
    assert len(due) == 1
    assert due[0].id == r.id


async def test_get_due_auto_archive_excludes_acknowledged(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 5, 1, tzinfo=UTC))
    r.is_sent = True
    r.is_acknowledged = True
    r.auto_archive_at = datetime(2026, 5, 2, tzinfo=UTC)
    await db_session.commit()

    now = datetime(2026, 6, 1, tzinfo=UTC)
    due = await repo.get_due_auto_archive(now)
    assert len(due) == 0


async def test_get_due_auto_archive_excludes_already_completed(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 5, 1, tzinfo=UTC))
    r.is_sent = True
    r.is_auto_completed = True
    r.auto_archive_at = datetime(2026, 5, 2, tzinfo=UTC)
    await db_session.commit()

    now = datetime(2026, 6, 1, tzinfo=UTC)
    due = await repo.get_due_auto_archive(now)
    assert len(due) == 0


async def test_get_due_auto_archive_excludes_cancelled(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 5, 1, tzinfo=UTC))
    r.is_sent = True
    r.is_cancelled = True
    r.auto_archive_at = datetime(2026, 5, 2, tzinfo=UTC)
    await db_session.commit()

    now = datetime(2026, 6, 1, tzinfo=UTC)
    due = await repo.get_due_auto_archive(now)
    assert len(due) == 0


async def test_get_due_auto_archive_excludes_future(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 5, 1, tzinfo=UTC))
    r.is_sent = True
    r.auto_archive_at = datetime(2026, 12, 1, tzinfo=UTC)
    await db_session.commit()

    now = datetime(2026, 6, 1, tzinfo=UTC)
    due = await repo.get_due_auto_archive(now)
    assert len(due) == 0


async def test_set_auto_archive_at_persists(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    archive_at = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)
    await repo.set_auto_archive_at(r, archive_at)
    await db_session.commit()
    await db_session.refresh(r)

    assert r.auto_archive_at is not None


async def test_mark_auto_completed_sets_flag_and_clears_timer(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    r.is_sent = True
    r.auto_archive_at = datetime(2026, 6, 2, tzinfo=UTC)
    await db_session.commit()

    await repo.mark_auto_completed(r.id)
    await db_session.commit()
    await db_session.refresh(r)

    assert r.is_auto_completed is True
    assert r.auto_archive_at is None


async def test_mark_auto_completed_nonexistent_id_does_nothing(db_session: AsyncSession) -> None:
    repo = ReminderRepository(db_session)
    await repo.mark_auto_completed(uuid.uuid4())  # should not raise


async def test_reactivate_resets_state_and_returns_row(db_session: AsyncSession) -> None:
    """Reactivating an auto-completed reminder clears all close flags and resets remind_at."""
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    r.is_sent = True
    r.is_acknowledged = False
    r.is_auto_completed = True
    r.auto_archive_at = None
    await db_session.commit()

    new_at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    returned = await repo.reactivate(r.id, new_at)
    await db_session.commit()
    await db_session.refresh(r)

    assert returned is not None
    assert returned.id == r.id
    assert r.is_auto_completed is False
    assert r.is_acknowledged is False
    assert r.is_cancelled is False
    assert r.is_sent is False
    assert r.auto_archive_at is None
    assert r.remind_at.replace(tzinfo=None) == new_at.replace(tzinfo=None)


async def test_reactivate_nonexistent_id_returns_none(db_session: AsyncSession) -> None:
    repo = ReminderRepository(db_session)
    result = await repo.reactivate(uuid.uuid4(), datetime(2026, 6, 1, tzinfo=UTC))
    assert result is None


async def test_reset_auto_archive_at_clears_the_field(db_session: AsyncSession) -> None:
    """reset_auto_archive_at sets auto_archive_at to None on an existing reminder."""
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    r.is_sent = True
    r.auto_archive_at = datetime(2026, 6, 2, tzinfo=UTC)
    await db_session.commit()

    await repo.reset_auto_archive_at(r.id)
    await db_session.commit()
    await db_session.refresh(r)

    assert r.auto_archive_at is None


async def test_reset_auto_archive_at_nonexistent_id_does_nothing(db_session: AsyncSession) -> None:
    """reset_auto_archive_at does not raise when the reminder is not found."""
    repo = ReminderRepository(db_session)
    await repo.reset_auto_archive_at(uuid.uuid4())  # should not raise
