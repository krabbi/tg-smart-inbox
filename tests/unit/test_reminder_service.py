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


async def test_cancel_calls_repo_and_commits() -> None:
    svc, repo, session = make_service()
    reminder_id = uuid.uuid4()
    repo.cancel = AsyncMock()

    await svc.cancel(reminder_id)

    repo.cancel.assert_awaited_once_with(reminder_id)
    session.commit.assert_awaited_once()


async def test_mark_sent_sets_flag_and_commits() -> None:
    svc, _, session = make_service()
    reminder = MagicMock(spec=Reminder)
    reminder.is_sent = False

    await svc.mark_sent(reminder)

    assert reminder.is_sent is True
    session.commit.assert_awaited_once()
