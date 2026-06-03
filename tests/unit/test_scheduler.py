from unittest.mock import AsyncMock, MagicMock, patch

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.scheduler import _auto_archive_reminders, _send_due_reminders, start_scheduler
from bot.services.reindex_service import ReindexService


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
        mock_svc.mark_sent_with_auto_archive = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_repo_cls.return_value = MagicMock()
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="Europe/Moscow")
        mock_settings.get_language = AsyncMock(return_value="ru")
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
    mock_settings.get_language.assert_awaited_once_with(123)
    mock_svc.mark_sent_with_auto_archive.assert_awaited_once()


async def test_send_due_reminders_schedules_auto_archive_24h_later() -> None:
    """When a reminder is sent, the auto-archive timer is set to now+24h, not 5min."""
    from datetime import UTC, datetime, timedelta

    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 1
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
        mock_svc.mark_sent_with_auto_archive = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="UTC")
        mock_settings.get_language = AsyncMock(return_value="en")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        before = datetime.now(UTC)
        await _send_due_reminders(bot, factory)
        after = datetime.now(UTC)

    archive_at = mock_svc.mark_sent_with_auto_archive.call_args[0][1]
    # The scheduled archive time must fall in [before+24h, after+24h] — confirms
    # that the new 24h window (not the legacy 5min window) is being used.
    assert before + timedelta(hours=24) <= archive_at <= after + timedelta(hours=24)


async def test_send_due_reminders_uses_user_language_for_notification() -> None:
    """The notification text must be localized to the user's stored language."""
    from datetime import UTC, datetime

    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 77
    item.content = "buy milk"

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
        mock_svc.mark_sent_with_auto_archive = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_repo_cls.return_value = MagicMock()
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="UTC")
        mock_settings.get_language = AsyncMock(return_value="en")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _send_due_reminders(bot, factory)

    call_kwargs = bot.send_message.call_args[1]
    # English notification template begins with "🔔 Reminder …" — verifies i18n path.
    assert "Reminder" in call_kwargs["text"]
    # Snooze keyboard buttons also must be localized.
    rows = call_kwargs["reply_markup"].inline_keyboard
    texts = [b.text for row in rows for b in row]
    assert any("+1h" in t for t in texts)
    assert any("Done" in t for t in texts)


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
        mock_svc.mark_sent_with_auto_archive = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="UTC")
        mock_settings.get_language = AsyncMock(return_value="en")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=Exception("Telegram error"))
        factory = make_session_factory(session)

        # Should not raise — errors are logged and swallowed
        await _send_due_reminders(bot, factory)

    mock_svc.mark_sent_with_auto_archive.assert_not_awaited()


async def test_auto_archive_marks_completed_and_notifies_with_reactivate_button() -> None:
    """An overdue auto-archive reminder is closed and the user gets a Reactivate keyboard."""
    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 42
    item.content = "купить молоко"

    reminder = MagicMock(spec=Reminder)
    reminder.id = "rid"
    reminder.item_id = "iid"

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository"),
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
        patch("bot.scheduler.UserSettingsService") as mock_settings_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due_auto_archive = AsyncMock(return_value=[reminder])
        mock_svc.mark_auto_completed = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        mock_settings = MagicMock()
        mock_settings.get_language = AsyncMock(return_value="ru")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _auto_archive_reminders(bot, factory)

    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == 42
    assert "автоматически" in call_kwargs["text"]
    assert "купить молоко" in call_kwargs["text"]
    # Single-button keyboard with the reactivate callback.
    rows = call_kwargs["reply_markup"].inline_keyboard
    buttons = [b for row in rows for b in row]
    assert len(buttons) == 1
    assert buttons[0].callback_data.startswith("remind_reactivate:")
    assert "Реактивировать" in buttons[0].text

    mock_svc.mark_auto_completed.assert_awaited_once_with(reminder)


async def test_auto_archive_uses_user_language() -> None:
    """The auto-archive notification is localized to the user's stored language."""
    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 55
    item.content = "buy milk"

    reminder = MagicMock(spec=Reminder)
    reminder.id = "rid"
    reminder.item_id = "iid"

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository"),
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
        patch("bot.scheduler.UserSettingsService") as mock_settings_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due_auto_archive = AsyncMock(return_value=[reminder])
        mock_svc.mark_auto_completed = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        mock_settings = MagicMock()
        mock_settings.get_language = AsyncMock(return_value="en")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _auto_archive_reminders(bot, factory)

    text = bot.send_message.call_args[1]["text"]
    assert "automatically" in text


async def test_auto_archive_missing_item_still_marks_completed_silently() -> None:
    """When the parent Item is gone, the reminder is auto-completed without a push."""
    from bot.models.reminder import Reminder

    reminder = MagicMock(spec=Reminder)
    reminder.id = "rid"
    reminder.item_id = "iid"

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=None)

    with (
        patch("bot.scheduler.ReminderRepository"),
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due_auto_archive = AsyncMock(return_value=[reminder])
        mock_svc.mark_auto_completed = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _auto_archive_reminders(bot, factory)

    mock_svc.mark_auto_completed.assert_awaited_once_with(reminder)
    bot.send_message.assert_not_awaited()


async def test_auto_archive_handles_send_failure_without_raising() -> None:
    """Send errors are logged and swallowed; the row is not marked auto-completed."""
    from bot.models.item import Item
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 42
    item.content = "task"

    reminder = MagicMock(spec=Reminder)
    reminder.id = "rid"
    reminder.item_id = "iid"

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository"),
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
        patch("bot.scheduler.UserSettingsService") as mock_settings_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due_auto_archive = AsyncMock(return_value=[reminder])
        mock_svc.mark_auto_completed = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_language = AsyncMock(return_value="en")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=Exception("Telegram error"))
        factory = make_session_factory(session)

        await _auto_archive_reminders(bot, factory)

    # Failure must be swallowed — and because the send failed, we don't claim
    # the reminder is closed (the next tick will retry).
    mock_svc.mark_auto_completed.assert_not_awaited()


def test_start_scheduler_returns_scheduler() -> None:
    bot = MagicMock()
    factory = MagicMock()
    with patch.object(AsyncIOScheduler, "start"):
        scheduler = start_scheduler(bot, factory)
    assert isinstance(scheduler, AsyncIOScheduler)


def test_start_scheduler_registers_two_jobs_without_config() -> None:
    bot = MagicMock()
    factory = MagicMock()
    with patch.object(AsyncIOScheduler, "start"):
        scheduler = start_scheduler(bot, factory)
    # send_due + auto_archive = 2 jobs (no reindex job without config).
    assert len(scheduler.get_jobs()) == 2


def test_start_scheduler_registers_reindex_job_when_config_given() -> None:
    from bot.config import Config

    bot = MagicMock()
    factory = MagicMock()
    config = Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")
    with patch.object(AsyncIOScheduler, "start"):
        scheduler = start_scheduler(bot, factory, config)
    # Reminders + auto-archive + reindex = 3 jobs
    assert len(scheduler.get_jobs()) == 3


def test_start_scheduler_reindex_job_waits_for_first_interval() -> None:
    from bot.config import Config

    bot = MagicMock()
    factory = MagicMock()
    config = Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")
    with (
        patch.object(AsyncIOScheduler, "add_job") as mock_add_job,
        patch.object(AsyncIOScheduler, "start"),
    ):
        start_scheduler(bot, factory, config)

    reindex_job_kwargs = mock_add_job.call_args_list[2].kwargs
    assert reindex_job_kwargs["trigger"] == "interval"
    assert reindex_job_kwargs["minutes"] == 10
    assert "next_run_time" not in reindex_job_kwargs


def test_start_scheduler_does_not_register_a_legacy_auto_resend_job() -> None:
    """The 5-minute auto-resend behaviour must be gone — no such job is registered."""
    import bot.scheduler as scheduler_mod

    # The legacy private symbol no longer exists on the module.
    assert not hasattr(scheduler_mod, "_auto_resend_reminders")
    assert not hasattr(scheduler_mod, "_MAX_AUTO_RESENDS")


async def test_reindex_missing_embeddings_processes_items_and_ideas() -> None:
    import uuid

    from bot.config import Config
    from bot.models.idea import Idea
    from bot.models.item import Item
    from bot.scheduler import _reindex_missing_embeddings

    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.content = "content"
    item.description = None
    item.scraped_text = None

    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = ["tag1"]
    parent = MagicMock(spec=Item)
    parent.content = "parent content"

    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    config = Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")

    with (
        patch("bot.scheduler.ItemRepository") as mock_item_repo_cls,
        patch("bot.scheduler.IdeaRepository") as mock_idea_repo_cls,
        patch("bot.scheduler.EmbeddingService") as mock_svc_cls,
    ):
        mock_item_repo = MagicMock()
        mock_item_repo.get_missing_embedding = AsyncMock(return_value=[item])
        mock_item_repo.update_embedding = AsyncMock()
        mock_item_repo_cls.return_value = mock_item_repo

        mock_idea_repo = MagicMock()
        mock_idea_repo.get_missing_embedding = AsyncMock(return_value=[(parent, idea)])
        mock_idea_repo.update_embedding = AsyncMock()
        mock_idea_repo_cls.return_value = mock_idea_repo

        mock_svc = MagicMock()
        mock_svc.generate_for_item = AsyncMock(return_value=[0.1, 0.2])
        mock_svc.generate_for_idea = AsyncMock(return_value=[0.3, 0.4])
        mock_svc_cls.return_value = mock_svc

        factory = make_session_factory(session)

        await _reindex_missing_embeddings(factory, config)

        mock_svc.generate_for_item.assert_awaited_once_with(item)
        mock_svc.generate_for_idea.assert_awaited_once_with(idea)
        mock_item_repo.update_embedding.assert_awaited_once_with(item.id, [0.1, 0.2])
        mock_idea_repo.update_embedding.assert_awaited_once_with(idea.id, [0.3, 0.4])


async def test_reindex_missing_embeddings_skips_when_user_reindex_is_running() -> None:
    from bot.config import Config
    from bot.scheduler import _reindex_missing_embeddings

    ReindexService._reset_running_state()
    assert ReindexService.try_start_user_reindex(42)
    factory = MagicMock(spec=async_sessionmaker)
    config = Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")

    try:
        with patch("bot.scheduler.EmbeddingService") as mock_svc_cls:
            await _reindex_missing_embeddings(factory, config)
    finally:
        ReindexService._reset_running_state()

    factory.assert_not_called()
    mock_svc_cls.assert_not_called()


async def test_reindex_missing_embeddings_releases_scheduler_lock_on_outer_error() -> None:
    from bot.config import Config
    from bot.scheduler import _reindex_missing_embeddings

    ReindexService._reset_running_state()
    factory = MagicMock(side_effect=RuntimeError("session failed"))
    config = Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")

    raised = False
    try:
        await _reindex_missing_embeddings(factory, config)
    except RuntimeError:
        raised = True

    assert raised
    assert not ReindexService.is_reindex_running()


async def test_reindex_missing_embeddings_skips_failed_record_and_continues() -> None:
    """A single item crashing the embedding pipeline must not stop the whole batch."""
    import uuid

    from bot.config import Config
    from bot.models.item import Item
    from bot.scheduler import _reindex_missing_embeddings

    good_item = MagicMock(spec=Item)
    good_item.id = uuid.uuid4()
    good_item.content = "good"
    good_item.description = None
    good_item.scraped_text = None

    bad_item = MagicMock(spec=Item)
    bad_item.id = uuid.uuid4()
    bad_item.content = "bad"
    bad_item.description = None
    bad_item.scraped_text = None

    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    config = Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")

    with (
        patch("bot.scheduler.ItemRepository") as mock_item_repo_cls,
        patch("bot.scheduler.IdeaRepository") as mock_idea_repo_cls,
        patch("bot.scheduler.EmbeddingService") as mock_svc_cls,
    ):
        mock_item_repo = MagicMock()
        mock_item_repo.get_missing_embedding = AsyncMock(return_value=[bad_item, good_item])
        mock_item_repo.update_embedding = AsyncMock()
        mock_item_repo_cls.return_value = mock_item_repo

        mock_idea_repo = MagicMock()
        mock_idea_repo.get_missing_embedding = AsyncMock(return_value=[])
        mock_idea_repo_cls.return_value = mock_idea_repo

        mock_svc = MagicMock()
        # First call (bad_item) raises, second call (good_item) returns vector
        mock_svc.generate_for_item = AsyncMock(side_effect=[Exception("API down"), [0.5, 0.6]])
        mock_svc_cls.return_value = mock_svc

        factory = make_session_factory(session)

        # Must not raise — errors are swallowed per record
        await _reindex_missing_embeddings(factory, config)

        # The good item was still indexed even though the bad one failed.
        mock_item_repo.update_embedding.assert_awaited_once_with(good_item.id, [0.5, 0.6])
        session.rollback.assert_awaited()


async def test_reindex_missing_embeddings_throttles_between_successful_calls() -> None:
    """Reindex sleeps after each successful embedding to stay below Voyage AI rate limits."""
    import uuid

    from bot.config import Config
    from bot.models.idea import Idea
    from bot.models.item import Item
    from bot.scheduler import _REINDEX_THROTTLE_SECONDS, _reindex_missing_embeddings

    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.content = "content"
    item.description = None
    item.scraped_text = None

    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = ["tag1"]
    parent = MagicMock(spec=Item)
    parent.content = "parent content"

    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    config = Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")

    with (
        patch("bot.scheduler.ItemRepository") as mock_item_repo_cls,
        patch("bot.scheduler.IdeaRepository") as mock_idea_repo_cls,
        patch("bot.scheduler.EmbeddingService") as mock_svc_cls,
        patch("bot.scheduler.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        mock_item_repo = MagicMock()
        mock_item_repo.get_missing_embedding = AsyncMock(return_value=[item])
        mock_item_repo.update_embedding = AsyncMock()
        mock_item_repo_cls.return_value = mock_item_repo

        mock_idea_repo = MagicMock()
        mock_idea_repo.get_missing_embedding = AsyncMock(return_value=[(parent, idea)])
        mock_idea_repo.update_embedding = AsyncMock()
        mock_idea_repo_cls.return_value = mock_idea_repo

        mock_svc = MagicMock()
        mock_svc.generate_for_item = AsyncMock(return_value=[0.1, 0.2])
        mock_svc.generate_for_idea = AsyncMock(return_value=[0.3, 0.4])
        mock_svc_cls.return_value = mock_svc

        factory = make_session_factory(session)

        await _reindex_missing_embeddings(factory, config)

    # One throttle per successful record (item + idea = 2 sleeps).
    assert mock_sleep.await_count == 2
    mock_sleep.assert_any_await(_REINDEX_THROTTLE_SECONDS)


async def test_reindex_missing_embeddings_does_not_throttle_on_none_vector() -> None:
    """When ``generate_for_*`` returns ``None``, no throttle sleep is applied."""
    import uuid

    from bot.config import Config
    from bot.models.item import Item
    from bot.scheduler import _reindex_missing_embeddings

    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.content = "content"
    item.description = None
    item.scraped_text = None

    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    config = Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")

    with (
        patch("bot.scheduler.ItemRepository") as mock_item_repo_cls,
        patch("bot.scheduler.IdeaRepository") as mock_idea_repo_cls,
        patch("bot.scheduler.EmbeddingService") as mock_svc_cls,
        patch("bot.scheduler.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        mock_item_repo = MagicMock()
        mock_item_repo.get_missing_embedding = AsyncMock(return_value=[item])
        mock_item_repo.update_embedding = AsyncMock()
        mock_item_repo_cls.return_value = mock_item_repo

        mock_idea_repo = MagicMock()
        mock_idea_repo.get_missing_embedding = AsyncMock(return_value=[])
        mock_idea_repo_cls.return_value = mock_idea_repo

        mock_svc = MagicMock()
        mock_svc.generate_for_item = AsyncMock(return_value=None)
        mock_svc_cls.return_value = mock_svc

        factory = make_session_factory(session)

        await _reindex_missing_embeddings(factory, config)

    mock_sleep.assert_not_awaited()


async def test_send_due_reminders_uses_link_title_in_notification() -> None:
    """A reminder on a link with a stored title shows ``{title} ({url})`` in the push."""
    from datetime import UTC, datetime

    from bot.models.item import Item, ItemType
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 7
    item.content = "https://example.com/article"
    item.type = ItemType.link
    item.title = "Cool Article"
    item.description = None

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
        mock_svc.mark_sent_with_auto_archive = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="UTC")
        mock_settings.get_language = AsyncMock(return_value="ru")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _send_due_reminders(bot, factory)

    text = bot.send_message.call_args[1]["text"]
    assert "Cool Article (https://example.com/article)" in text


async def test_send_due_reminders_link_without_title_shows_bare_url() -> None:
    """A link reminder without a stored title sends the bare URL — graceful fallback."""
    from datetime import UTC, datetime

    from bot.models.item import Item, ItemType
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 7
    item.content = "https://example.com/raw"
    item.type = ItemType.link
    item.title = None
    item.description = None

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
        mock_svc.mark_sent_with_auto_archive = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="UTC")
        mock_settings.get_language = AsyncMock(return_value="ru")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _send_due_reminders(bot, factory)

    text = bot.send_message.call_args[1]["text"]
    assert "https://example.com/raw" in text
    # Bare URL — no parenthesis wrapping a duplicate URL.
    assert "https://example.com/raw (" not in text


async def test_auto_archive_link_uses_title_in_notification() -> None:
    """Auto-archive notifications for links use the title-aware display."""
    from bot.models.item import Item, ItemType
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 8
    item.content = "https://example.com/old-article"
    item.type = ItemType.link
    item.title = "Old Article"
    item.description = None

    reminder = MagicMock(spec=Reminder)
    reminder.id = "rid"
    reminder.item_id = "iid"

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository"),
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
        patch("bot.scheduler.UserSettingsService") as mock_settings_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due_auto_archive = AsyncMock(return_value=[reminder])
        mock_svc.mark_auto_completed = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_language = AsyncMock(return_value="ru")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _auto_archive_reminders(bot, factory)

    text = bot.send_message.call_args[1]["text"]
    assert "Old Article (https://example.com/old-article)" in text


async def test_send_due_reminders_link_with_summary_shows_inline_summary() -> None:
    """A link reminder with a stored summary shows the short summary in the notification."""
    from datetime import UTC, datetime

    from bot.models.item import Item, ItemType
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 9
    item.content = "https://example.com/article"
    item.type = ItemType.link
    item.title = "Cool Article"
    item.description = None
    item.summary = "This article explains everything you need to know about the topic."

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
        mock_svc.mark_sent_with_auto_archive = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="UTC")
        mock_settings.get_language = AsyncMock(return_value="en")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _send_due_reminders(bot, factory)

    text = bot.send_message.call_args[1]["text"]
    assert "Cool Article (https://example.com/article)" in text
    assert "This article explains everything" in text


async def test_send_due_reminders_link_without_summary_no_extra_line() -> None:
    """A link reminder without a stored summary shows only the title/URL line."""
    from datetime import UTC, datetime

    from bot.models.item import Item, ItemType
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 10
    item.content = "https://example.com/no-summary"
    item.type = ItemType.link
    item.title = "No Summary Article"
    item.description = None
    item.summary = None

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
        mock_svc.mark_sent_with_auto_archive = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_timezone = AsyncMock(return_value="UTC")
        mock_settings.get_language = AsyncMock(return_value="en")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _send_due_reminders(bot, factory)

    text = bot.send_message.call_args[1]["text"]
    assert "No Summary Article (https://example.com/no-summary)" in text
    # No extra summary line — the notification ends after the title/URL.
    lines_after_header = text.split("\n")
    assert not any("None" in line for line in lines_after_header)


async def test_auto_archive_link_with_summary_shows_inline_summary() -> None:
    """Auto-archive notifications for links with a summary include the short summary."""
    from bot.models.item import Item, ItemType
    from bot.models.reminder import Reminder

    item = MagicMock(spec=Item)
    item.user_id = 11
    item.content = "https://example.com/archived"
    item.type = ItemType.link
    item.title = "Archived Article"
    item.description = None
    item.summary = "A short description of the archived article."

    reminder = MagicMock(spec=Reminder)
    reminder.id = "rid"
    reminder.item_id = "iid"

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=item)

    with (
        patch("bot.scheduler.ReminderRepository"),
        patch("bot.scheduler.ReminderService") as mock_svc_cls,
        patch("bot.scheduler.UserSettingsService") as mock_settings_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_due_auto_archive = AsyncMock(return_value=[reminder])
        mock_svc.mark_auto_completed = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        mock_settings = MagicMock()
        mock_settings.get_language = AsyncMock(return_value="en")
        mock_settings_cls.return_value = mock_settings

        bot = MagicMock()
        bot.send_message = AsyncMock()
        factory = make_session_factory(session)

        await _auto_archive_reminders(bot, factory)

    text = bot.send_message.call_args[1]["text"]
    assert "Archived Article (https://example.com/archived)" in text
    assert "A short description of the archived article." in text


async def test_reindex_missing_embeddings_skips_none_vectors() -> None:
    """When the API returns None, the record is left untouched and no update happens."""
    import uuid

    from bot.config import Config
    from bot.models.item import Item
    from bot.scheduler import _reindex_missing_embeddings

    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.content = "content"
    item.description = None
    item.scraped_text = None

    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    config = Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")

    with (
        patch("bot.scheduler.ItemRepository") as mock_item_repo_cls,
        patch("bot.scheduler.IdeaRepository") as mock_idea_repo_cls,
        patch("bot.scheduler.EmbeddingService") as mock_svc_cls,
    ):
        mock_item_repo = MagicMock()
        mock_item_repo.get_missing_embedding = AsyncMock(return_value=[item])
        mock_item_repo.update_embedding = AsyncMock()
        mock_item_repo_cls.return_value = mock_item_repo

        mock_idea_repo = MagicMock()
        mock_idea_repo.get_missing_embedding = AsyncMock(return_value=[])
        mock_idea_repo_cls.return_value = mock_idea_repo

        mock_svc = MagicMock()
        mock_svc.generate_for_item = AsyncMock(return_value=None)
        mock_svc_cls.return_value = mock_svc

        factory = make_session_factory(session)

        await _reindex_missing_embeddings(factory, config)

        mock_item_repo.update_embedding.assert_not_awaited()
