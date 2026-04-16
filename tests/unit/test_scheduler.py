from unittest.mock import AsyncMock, MagicMock, patch

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.scheduler import _auto_resend_reminders, _send_due_reminders, start_scheduler


def make_session_factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    factory = MagicMock(spec=async_sessionmaker)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = cm
    return factory


async def test_send_due_reminders_sends_notifications() -> None:
    from datetime import UTC, datetime

    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 123
    item.content = "купить молоко"

    reminder = MagicMock(spec=Reminder)
    reminder.id = "fake-id"
    reminder.item_id = "fake-item-id"
    reminder.remind_at = datetime(2026, 4, 7, 10, 0, tzinfo=UTC)

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository") as mock_repo_cls,
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
        patch("bot.scheduler.UserSettingsService") as mock_settings_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due = AsyncMock(return_value=[reminder])
        mock_svc.mark_sent_with_auto_resend = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_repo_cls.return_value = MagicMock()
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="Europe/Moscow")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _send_due_reminders(bot, factory)

    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == 123
    assert "купить молоко" in call_kwargs["text"]
    # User's timezone formatting flows into the notification text
    assert "13:00 MSK" in call_kwargs["text"]
    assert call_kwargs["reply_markup"] is not None
    mock_settings.get_timezone.assert_awaited_once_with(123)
    mock_svc.mark_sent_with_auto_resend.assert_awaited_once()


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
    from datetime import UTC, datetime

    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 123
    item.content = "task"
    reminder = MagicMock(spec=Reminder)
    reminder.id = "fake-id"
    reminder.item_id = "fake-item-id"
    reminder.remind_at = datetime(2026, 4, 7, 10, 0, tzinfo=UTC)

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository"),
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
        patch("bot.scheduler.UserSettingsService") as mock_settings_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due = AsyncMock(return_value=[reminder])
        mock_svc.mark_sent_with_auto_resend = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="UTC")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=Exception("Telegram error"))
        factory = make_session_factory(session)

        # Should not raise — errors are logged and swallowed
        await _send_due_reminders(bot, factory)

    mock_svc.mark_sent_with_auto_resend.assert_not_awaited()


async def test_auto_resend_reminders_creates_followup() -> None:
    from datetime import UTC, datetime

    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 42
    item.content = "задача"

    original = MagicMock(spec=Reminder)
    original.id = "orig-id"
    original.item_id = "item-id"
    original.snooze_count = 0

    new_reminder = MagicMock(spec=Reminder)
    new_reminder.id = "new-id"
    new_reminder.remind_at = datetime(2026, 4, 7, 10, 0, tzinfo=UTC)

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository") as mock_repo_cls,
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
        patch("bot.scheduler.UserSettingsService") as mock_settings_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due_auto_resend = AsyncMock(return_value=[original])
        mock_svc.prepare_auto_resend = AsyncMock(return_value=new_reminder)
        mock_svc.mark_sent_with_auto_resend = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_repo_cls.return_value = MagicMock()
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="UTC")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _auto_resend_reminders(bot, factory)

    mock_svc.prepare_auto_resend.assert_awaited_once()
    assert mock_svc.prepare_auto_resend.call_args[1]["original"] is original
    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == 42
    assert "задача" in call_kwargs["text"]
    assert "10:00 UTC" in call_kwargs["text"]
    mock_settings.get_timezone.assert_awaited_once_with(42)
    mock_svc.mark_sent_with_auto_resend.assert_awaited_once()


async def test_auto_resend_stops_after_max_resends() -> None:
    from bot.models.reminder import Reminder
    from bot.scheduler import _MAX_AUTO_RESENDS

    original = MagicMock(spec=Reminder)
    original.id = "orig-id"
    original.snooze_count = _MAX_AUTO_RESENDS  # already at limit

    session = MagicMock(spec=AsyncSession)

    with (
        patch("bot.scheduler.ReminderRepository") as mock_repo_cls,
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
    ):
        mock_repo_cls.return_value = MagicMock()

        mock_svc = MagicMock()
        mock_svc.get_due_auto_resend = AsyncMock(return_value=[original])
        mock_svc.mark_acknowledged = AsyncMock()
        mock_svc.prepare_auto_resend = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _auto_resend_reminders(bot, factory)

    mock_svc.mark_acknowledged.assert_awaited_once_with(original)
    mock_svc.prepare_auto_resend.assert_not_awaited()
    bot.send_message.assert_not_awaited()


def test_start_scheduler_returns_scheduler() -> None:
    bot = MagicMock()
    factory = MagicMock()
    with patch.object(AsyncIOScheduler, "start"):
        scheduler = start_scheduler(bot, factory)
    assert isinstance(scheduler, AsyncIOScheduler)


def test_start_scheduler_registers_two_jobs() -> None:
    bot = MagicMock()
    factory = MagicMock()
    with patch.object(AsyncIOScheduler, "start"):
        scheduler = start_scheduler(bot, factory)
    assert len(scheduler.get_jobs()) == 2
