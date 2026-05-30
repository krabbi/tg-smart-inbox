import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.reminder import Reminder
from bot.repositories.reminder_repository import ReminderRepository
from bot.services.reminder_service import ReminderService


def make_service() -> tuple[ReminderService, ReminderRepository, AsyncSession]:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    repo = MagicMock(spec=ReminderRepository)
    svc = ReminderService(session=session, repo=repo)
    return svc, repo, session


async def test_create_saves_and_commits() -> None:
    svc, repo, session = make_service()
    item_id = uuid.uuid4()
    remind_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    mock_reminder = MagicMock(spec=Reminder)
    repo.create = AsyncMock(return_value=mock_reminder)

    result = await svc.create(item_id=item_id, remind_at=remind_at)

    repo.create.assert_awaited_once_with(item_id=item_id, remind_at=remind_at)
    session.commit.assert_awaited_once()
    assert result is mock_reminder


async def test_get_due_delegates_to_repo() -> None:
    svc, repo, _ = make_service()
    now = datetime(2026, 6, 1, tzinfo=UTC)
    expected = [MagicMock(spec=Reminder)]
    repo.get_due = AsyncMock(return_value=expected)

    result = await svc.get_due(now)

    repo.get_due.assert_awaited_once_with(now)
    assert result == expected


async def test_mark_sent_sets_flag_and_commits() -> None:
    svc, _, session = make_service()
    reminder = MagicMock(spec=Reminder)
    reminder.is_sent = False

    await svc.mark_sent(reminder)

    assert reminder.is_sent is True
    session.commit.assert_awaited_once()


async def test_mark_sent_with_auto_archive_commits() -> None:
    svc, repo, session = make_service()
    reminder = MagicMock(spec=Reminder)
    reminder.is_sent = False
    repo.set_auto_archive_at = AsyncMock()
    archive_at = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)

    await svc.mark_sent_with_auto_archive(reminder, archive_at)

    assert reminder.is_sent is True
    repo.set_auto_archive_at.assert_awaited_once_with(reminder, archive_at)
    session.commit.assert_awaited_once()


async def test_get_due_auto_archive_delegates_to_repo() -> None:
    svc, repo, _ = make_service()
    now = datetime(2026, 6, 1, tzinfo=UTC)
    expected = [MagicMock(spec=Reminder)]
    repo.get_due_auto_archive = AsyncMock(return_value=expected)

    result = await svc.get_due_auto_archive(now)

    repo.get_due_auto_archive.assert_awaited_once_with(now)
    assert result == expected


async def test_snooze_acknowledges_and_creates_new() -> None:
    svc, repo, session = make_service()
    reminder_id = uuid.uuid4()
    item_id = uuid.uuid4()
    remind_at = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)

    original = MagicMock(spec=Reminder)
    original.item_id = item_id
    original.snooze_count = 1

    repo.get_by_id_for_user = AsyncMock(return_value=original)
    repo.acknowledge = AsyncMock()
    new_reminder = MagicMock(spec=Reminder)
    new_reminder.snooze_count = 0
    repo.create = AsyncMock(return_value=new_reminder)
    session.flush = AsyncMock()

    result = await svc.snooze(reminder_id=reminder_id, user_id=1, remind_at=remind_at)

    assert result is True
    repo.acknowledge.assert_awaited_once_with(reminder_id)
    repo.create.assert_awaited_once_with(item_id=item_id, remind_at=remind_at)
    assert new_reminder.snooze_count == 2
    session.commit.assert_awaited_once()


async def test_snooze_returns_false_when_not_owned() -> None:
    svc, repo, session = make_service()
    repo.get_by_id_for_user = AsyncMock(return_value=None)

    result = await svc.snooze(
        reminder_id=uuid.uuid4(), user_id=999, remind_at=datetime(2026, 6, 1, tzinfo=UTC)
    )

    assert result is False
    session.commit.assert_not_awaited()


async def test_acknowledge_acknowledges_and_commits() -> None:
    svc, repo, session = make_service()
    reminder_id = uuid.uuid4()
    reminder = MagicMock(spec=Reminder)
    repo.get_by_id_for_user = AsyncMock(return_value=reminder)
    repo.acknowledge = AsyncMock()

    result = await svc.acknowledge(reminder_id=reminder_id, user_id=1)

    assert result is True
    repo.acknowledge.assert_awaited_once_with(reminder_id)
    session.commit.assert_awaited_once()


async def test_acknowledge_returns_false_when_not_owned() -> None:
    svc, repo, session = make_service()
    repo.get_by_id_for_user = AsyncMock(return_value=None)

    result = await svc.acknowledge(reminder_id=uuid.uuid4(), user_id=999)

    assert result is False
    session.commit.assert_not_awaited()


async def test_mark_auto_completed_calls_repo_and_commits() -> None:
    svc, repo, session = make_service()
    reminder = MagicMock(spec=Reminder)
    reminder.id = uuid.uuid4()
    repo.mark_auto_completed = AsyncMock()

    await svc.mark_auto_completed(reminder)

    repo.mark_auto_completed.assert_awaited_once_with(reminder.id)
    session.commit.assert_awaited_once()


async def test_reactivate_for_user_returns_reminder_and_commits() -> None:
    svc, repo, session = make_service()
    reminder_id = uuid.uuid4()
    remind_at = datetime(2026, 6, 1, tzinfo=UTC)

    found = MagicMock(spec=Reminder)
    repo.get_by_id_for_user = AsyncMock(return_value=found)

    updated = MagicMock(spec=Reminder)
    repo.reactivate = AsyncMock(return_value=updated)

    result = await svc.reactivate_for_user(reminder_id=reminder_id, user_id=42, remind_at=remind_at)

    repo.get_by_id_for_user.assert_awaited_once_with(reminder_id, 42)
    repo.reactivate.assert_awaited_once_with(reminder_id, remind_at)
    session.commit.assert_awaited_once()
    assert result is updated


async def test_reactivate_for_user_returns_none_when_not_owned() -> None:
    svc, repo, session = make_service()
    repo.get_by_id_for_user = AsyncMock(return_value=None)
    repo.reactivate = AsyncMock()

    result = await svc.reactivate_for_user(
        reminder_id=uuid.uuid4(), user_id=999, remind_at=datetime(2026, 6, 1, tzinfo=UTC)
    )

    assert result is None
    repo.reactivate.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_reactivate_for_user_returns_none_when_row_disappears() -> None:
    """Defensive: if the row vanishes between ownership check and update, return None."""
    svc, repo, session = make_service()
    repo.get_by_id_for_user = AsyncMock(return_value=MagicMock(spec=Reminder))
    repo.reactivate = AsyncMock(return_value=None)

    result = await svc.reactivate_for_user(
        reminder_id=uuid.uuid4(), user_id=1, remind_at=datetime(2026, 6, 1, tzinfo=UTC)
    )

    assert result is None
    session.commit.assert_not_awaited()
