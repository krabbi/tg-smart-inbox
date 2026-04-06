from unittest.mock import AsyncMock, MagicMock, patch

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.scheduler import _send_due_reminders, start_scheduler


def make_session_factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    factory = MagicMock(spec=async_sessionmaker)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = cm
    return factory


async def test_send_due_reminders_sends_notifications() -> None:
    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 123
    item.content = "купить молоко"

    reminder = MagicMock(spec=Reminder)
    reminder.id = "fake-id"
    reminder.item_id = "fake-item-id"

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository") as mock_repo_cls,
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due = AsyncMock(return_value=[reminder])
        mock_svc.mark_sent = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        mock_repo_cls.return_value = MagicMock()

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _send_due_reminders(bot, factory)

    bot.send_message.assert_awaited_once_with(chat_id=123, text="🔔 Напоминание:\nкупить молоко")
    mock_svc.mark_sent.assert_awaited_once_with(reminder)


async def test_send_due_reminders_no_item_marks_sent() -> None:
    from bot.models.reminder import Reminder

    reminder = MagicMock(spec=Reminder)
    reminder.id = "fake-id"
    reminder.item_id = "fake-item-id"

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=None)

    with (
        patch("bot.scheduler.ReminderRepository"),
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due = AsyncMock(return_value=[reminder])
        mock_svc.mark_sent = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _send_due_reminders(bot, factory)

    bot.send_message.assert_not_awaited()
    mock_svc.mark_sent.assert_awaited_once_with(reminder)


async def test_send_due_reminders_handles_send_error() -> None:
    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 123
    item.content = "task"
    reminder = MagicMock(spec=Reminder)
    reminder.id = "fake-id"
    reminder.item_id = "fake-item-id"

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository"),
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due = AsyncMock(return_value=[reminder])
        mock_svc.mark_sent = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=Exception("Telegram error"))
        factory = make_session_factory(session)

        # Should not raise — errors are logged and swallowed
        await _send_due_reminders(bot, factory)

    mock_svc.mark_sent.assert_not_awaited()


def test_start_scheduler_returns_scheduler() -> None:
    bot = MagicMock()
    factory = MagicMock()
    with patch.object(AsyncIOScheduler, "start"):
        scheduler = start_scheduler(bot, factory)
    assert isinstance(scheduler, AsyncIOScheduler)
