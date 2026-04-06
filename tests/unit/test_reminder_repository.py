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


async def test_cancel_sets_flag(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="task")
    db_session.add(item)
    await db_session.flush()

    repo = ReminderRepository(db_session)
    r = await repo.create(item_id=item.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    await db_session.commit()

    await repo.cancel(r.id)
    await db_session.commit()
    await db_session.refresh(r)

    assert r.is_cancelled is True


async def test_cancel_nonexistent_id_does_nothing(db_session: AsyncSession) -> None:
    repo = ReminderRepository(db_session)
    await repo.cancel(uuid.uuid4())  # should not raise


async def test_get_by_user_pending(db_session: AsyncSession) -> None:
    item1 = Item(user_id=10, type=ItemType.task, content="task user 10")
    item2 = Item(user_id=20, type=ItemType.task, content="task user 20")
    db_session.add_all([item1, item2])
    await db_session.flush()

    repo = ReminderRepository(db_session)
    await repo.create(item_id=item1.id, remind_at=datetime(2026, 6, 1, tzinfo=UTC))
    await repo.create(item_id=item2.id, remind_at=datetime(2026, 6, 2, tzinfo=UTC))
    await db_session.commit()

    results = await repo.get_by_user_pending(10)
    assert len(results) == 1
    assert results[0].item_id == item1.id
