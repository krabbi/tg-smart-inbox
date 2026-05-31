"""Tests for /list, /reminders, /cancel command handlers."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.handlers import commands as commands_module
from bot.handlers.commands import (
    _list_keyboard,
    _parse_type_suffix,
    cb_cancel_reminder,
    cb_list_filter,
    cb_list_page,
    cmd_cancel,
    cmd_list,
    cmd_reindex,
    cmd_reminders,
)
from bot.models.item import Item, ItemType
from bot.models.reminder import Reminder
from bot.services.embedding_service import EmbeddingService
from bot.services.list_service import ListPage, ListService
from bot.services.reindex_service import ReindexService, ReindexSummary
from bot.services.reminder_service import ReminderService
from bot.services.user_settings_service import UserSettingsService


def make_message(user_id: int = 1) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    return msg


def make_callback(data: str, user_id: int = 1) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = MagicMock()
    cb.message.text = "original text"
    cb.message.edit_text = AsyncMock()
    return cb


def make_item(
    content: str,
    item_type: ItemType = ItemType.note,
    *,
    title: str | None = None,
    description: str | None = None,
) -> MagicMock:
    item = MagicMock(spec=Item)
    item.content = content
    item.type = item_type
    item.title = title
    item.description = description
    item.created_at = MagicMock()
    item.created_at.strftime = MagicMock(return_value="01.01.2026")
    return item


def make_reminder(
    content: str,
    reminder_id: uuid.UUID | None = None,
    remind_at: datetime | None = None,
    *,
    item_type: ItemType = ItemType.task,
    title: str | None = None,
    description: str | None = None,
) -> MagicMock:
    r = MagicMock(spec=Reminder)
    r.id = reminder_id or uuid.uuid4()
    r.item = MagicMock(spec=Item)
    r.item.content = content
    r.item.type = item_type
    r.item.title = title
    r.item.description = description
    r.remind_at = remind_at or datetime(2026, 4, 7, 10, 0, tzinfo=UTC)
    return r


def make_list_page(items: list, page: int = 0, total: int | None = None) -> ListPage:
    return ListPage(items=items, page=page, total=total if total is not None else len(items))


# ── /list ─────────────────────────────────────────────────────────────────────


async def test_cmd_list_no_service_gives_stub() -> None:
    msg = make_message()
    await cmd_list(msg, list_service=None, lang="ru")
    assert "скоро" in msg.answer.call_args[0][0]


async def test_cmd_list_empty_gives_friendly_message() -> None:
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(return_value=make_list_page([], total=0))

    await cmd_list(msg, list_service=svc, lang="ru")
    assert "ничего не сохранено" in msg.answer.call_args[0][0].lower()


async def test_cmd_list_shows_items() -> None:
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page(
            [make_item("cool link", ItemType.link), make_item("buy milk", ItemType.task)], total=2
        )
    )

    await cmd_list(msg, list_service=svc, lang="ru")
    reply = msg.answer.call_args[0][0]
    assert "cool link" in reply
    assert "buy milk" in reply
    assert "🔗" in reply
    assert "✅" in reply


async def test_cmd_list_no_nav_buttons_for_single_page() -> None:
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page([make_item("x") for _ in range(3)], total=3)
    )

    await cmd_list(msg, list_service=svc, lang="ru")
    _, kwargs = msg.answer.call_args
    kb = kwargs.get("reply_markup")
    assert kb is not None
    # Should have filter row but no nav row
    assert len(kb.inline_keyboard) == 1
    # Filter buttons should be present
    texts = [b.text for b in kb.inline_keyboard[0]]
    assert any("Все" in t for t in texts)


async def test_cmd_list_link_with_title_shows_title_and_url() -> None:
    """A link with a saved title renders as ``{title} ({url})`` in /list."""
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page(
            [
                make_item(
                    "https://money.onliner.by/lunar",
                    ItemType.link,
                    title="Лунные участки",
                )
            ],
            total=1,
        )
    )

    await cmd_list(msg, list_service=svc, lang="ru")
    reply = msg.answer.call_args[0][0]
    assert "Лунные участки (https://money.onliner.by/lunar)" in reply


async def test_cmd_list_link_without_title_shows_bare_url() -> None:
    """Links without a stored title display the raw URL — graceful fallback."""
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page(
            [make_item("https://example.com", ItemType.link, title=None)], total=1
        )
    )

    await cmd_list(msg, list_service=svc, lang="ru")
    reply = msg.answer.call_args[0][0]
    assert "https://example.com" in reply
    # No parentheses around a single URL — it's rendered alone.
    assert "https://example.com (" not in reply


async def test_cmd_list_media_with_description_shows_drive_link() -> None:
    """Media items show ``{description} ({drive_link})`` so the user knows what's inside."""
    msg = make_message()
    svc = MagicMock(spec=ListService)
    drive = "https://drive.google.com/file/d/abc"
    svc.list_recent = AsyncMock(
        return_value=make_list_page(
            [make_item(drive, ItemType.media, description="Чек из магазина")], total=1
        )
    )

    await cmd_list(msg, list_service=svc, lang="ru")
    reply = msg.answer.call_args[0][0]
    assert f"Чек из магазина ({drive})" in reply


async def test_cmd_list_shows_next_button_when_more() -> None:
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page([make_item(f"item {i}") for i in range(10)], total=15)
    )

    await cmd_list(msg, list_service=svc, lang="ru")
    _, kwargs = msg.answer.call_args
    kb = kwargs.get("reply_markup")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)


# ── cb_list_page ──────────────────────────────────────────────────────────────


async def test_cb_list_page_edits_message() -> None:
    cb = make_callback("list_page:1:all")
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page([make_item("item a")], page=1, total=15)
    )

    await cb_list_page(cb, list_service=svc, lang="ru")
    cb.message.edit_text.assert_awaited_once()
    svc.list_recent.assert_awaited_once_with(cb.from_user.id, page=1, item_type=None)


async def test_cb_list_page_with_type_filter() -> None:
    cb = make_callback("list_page:0:link")
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=ListPage(
            items=[make_item("http://ex.com", ItemType.link)],
            page=0,
            total=1,
            item_type=ItemType.link,
        )
    )

    await cb_list_page(cb, list_service=svc, lang="ru")
    svc.list_recent.assert_awaited_once_with(cb.from_user.id, page=0, item_type=ItemType.link)


async def test_cb_list_page_without_type_suffix() -> None:
    cb = make_callback("list_page:1")
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page([make_item("item a")], page=1, total=15)
    )

    await cb_list_page(cb, list_service=svc, lang="ru")
    svc.list_recent.assert_awaited_once_with(cb.from_user.id, page=1, item_type=None)


async def test_cb_list_page_invalid_data_is_ignored() -> None:
    cb = make_callback("list_page:notanint")
    svc = MagicMock(spec=ListService)

    await cb_list_page(cb, list_service=svc, lang="ru")
    svc.list_recent.assert_not_awaited()


async def test_cb_list_page_edit_failure_is_silenced() -> None:
    cb = make_callback("list_page:0:all")
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(return_value=make_list_page([make_item("x")], page=0, total=5))
    cb.message.edit_text = AsyncMock(side_effect=Exception("Message not modified"))

    # Should not raise
    await cb_list_page(cb, list_service=svc, lang="ru")


# ── /reminders ────────────────────────────────────────────────────────────────


async def test_cmd_reminders_no_service_gives_stub() -> None:
    msg = make_message()
    await cmd_reminders(msg, reminder_service=None, lang="ru")
    assert "скоро" in msg.answer.call_args[0][0]


async def test_cmd_reminders_empty() -> None:
    msg = make_message()
    svc = MagicMock(spec=ReminderService)
    svc.get_upcoming = AsyncMock(return_value=[])

    await cmd_reminders(msg, reminder_service=svc, lang="ru")
    text = msg.answer.call_args[0][0]
    assert "нет" in text.lower()
    # Empty list should also include a hint how to create the first reminder.
    assert "Отправь задачу" in text
    assert "чтобы создать напоминание" in text


async def test_cmd_reminders_shows_list() -> None:
    msg = make_message()
    svc = MagicMock(spec=ReminderService)
    svc.get_upcoming = AsyncMock(
        return_value=[make_reminder("buy milk"), make_reminder("call dentist")]
    )

    await cmd_reminders(msg, reminder_service=svc, lang="ru")
    assert msg.answer.await_count == 2
    calls = [c[0][0] for c in msg.answer.call_args_list]
    assert any("buy milk" in c for c in calls)
    assert any("call dentist" in c for c in calls)
    # Default formatting (no user_settings_service) shows UTC label.
    assert all("UTC" in c for c in calls)


async def test_cmd_reminders_uses_user_timezone() -> None:
    """Reminder times are converted to the user's timezone before display."""
    msg = make_message(user_id=42)
    svc = MagicMock(spec=ReminderService)
    svc.get_upcoming = AsyncMock(
        return_value=[make_reminder("buy milk", remind_at=datetime(2026, 4, 7, 10, 0, tzinfo=UTC))]
    )
    settings_svc = MagicMock(spec=UserSettingsService)
    settings_svc.get_timezone = AsyncMock(return_value="Europe/Moscow")

    await cmd_reminders(msg, reminder_service=svc, user_settings_service=settings_svc, lang="ru")

    settings_svc.get_timezone.assert_awaited_once_with(42)
    text = msg.answer.call_args[0][0]
    # 10:00 UTC → 13:00 MSK
    assert "07.04.2026 13:00 MSK" in text


async def test_cmd_reminders_link_with_title_shows_title_and_url() -> None:
    """A reminder on a link Item renders the article title with the URL in parentheses."""
    msg = make_message()
    svc = MagicMock(spec=ReminderService)
    svc.get_upcoming = AsyncMock(
        return_value=[
            make_reminder(
                "https://example.com/news",
                item_type=ItemType.link,
                title="Important news",
            )
        ]
    )

    await cmd_reminders(msg, reminder_service=svc, lang="ru")
    text = msg.answer.call_args[0][0]
    assert "Important news (https://example.com/news)" in text


async def test_cmd_reminders_link_without_title_shows_bare_url() -> None:
    """A link reminder with no stored title falls back to displaying just the URL."""
    msg = make_message()
    svc = MagicMock(spec=ReminderService)
    svc.get_upcoming = AsyncMock(
        return_value=[
            make_reminder(
                "https://example.com",
                item_type=ItemType.link,
                title=None,
            )
        ]
    )

    await cmd_reminders(msg, reminder_service=svc, lang="ru")
    text = msg.answer.call_args[0][0]
    assert "https://example.com" in text
    # Single-URL line — no "(...)" parenthetical.
    assert "https://example.com (" not in text


async def test_cmd_reminders_falls_back_to_utc_without_settings_service() -> None:
    """When user_settings_service is None, formatting falls back to UTC."""
    msg = make_message()
    svc = MagicMock(spec=ReminderService)
    svc.get_upcoming = AsyncMock(
        return_value=[make_reminder("buy milk", remind_at=datetime(2026, 4, 7, 10, 0, tzinfo=UTC))]
    )

    await cmd_reminders(msg, reminder_service=svc, user_settings_service=None, lang="ru")

    text = msg.answer.call_args[0][0]
    assert "07.04.2026 10:00 UTC" in text


# ── cb_cancel_reminder ────────────────────────────────────────────────────────


async def test_cb_cancel_reminder_cancels_and_edits() -> None:
    rid = uuid.uuid4()
    cb = make_callback(f"cancel_reminder:{rid}")
    svc = MagicMock(spec=ReminderService)
    svc.cancel_for_user = AsyncMock(return_value=True)

    await cb_cancel_reminder(cb, reminder_service=svc, lang="ru")
    svc.cancel_for_user.assert_awaited_once_with(rid, cb.from_user.id)
    cb.message.edit_text.assert_awaited_once()
    assert "отменено" in cb.message.edit_text.call_args[0][0].lower()


async def test_cb_cancel_reminder_not_owned_does_not_edit() -> None:
    rid = uuid.uuid4()
    cb = make_callback(f"cancel_reminder:{rid}")
    svc = MagicMock(spec=ReminderService)
    svc.cancel_for_user = AsyncMock(return_value=False)

    await cb_cancel_reminder(cb, reminder_service=svc, lang="ru")
    cb.message.edit_text.assert_not_awaited()


async def test_cb_cancel_reminder_invalid_uuid_is_safe() -> None:
    cb = make_callback("cancel_reminder:not-a-uuid")
    svc = MagicMock(spec=ReminderService)

    await cb_cancel_reminder(cb, reminder_service=svc, lang="ru")
    svc.cancel_for_user.assert_not_awaited()


async def test_cb_cancel_reminder_edit_failure_is_silenced() -> None:
    rid = uuid.uuid4()
    cb = make_callback(f"cancel_reminder:{rid}")
    svc = MagicMock(spec=ReminderService)
    svc.cancel_for_user = AsyncMock(return_value=True)
    cb.message.edit_text = AsyncMock(side_effect=Exception("Message deleted"))

    # Should not raise
    await cb_cancel_reminder(cb, reminder_service=svc, lang="ru")


# ── /cancel ───────────────────────────────────────────────────────────────────


async def test_cmd_cancel_with_active_state_clears_and_confirms() -> None:
    msg = make_message()
    state = MagicMock(spec=FSMContext)
    state.get_state = AsyncMock(return_value="reminders:waiting_for_time")
    state.clear = AsyncMock()

    await cmd_cancel(msg, state=state, lang="ru")

    state.clear.assert_awaited_once()
    assert "Отменено" in msg.answer.call_args[0][0]


async def test_cmd_cancel_with_no_active_state_notifies_user() -> None:
    msg = make_message()
    state = MagicMock(spec=FSMContext)
    state.get_state = AsyncMock(return_value=None)
    state.clear = AsyncMock()

    await cmd_cancel(msg, state=state, lang="ru")

    state.clear.assert_not_awaited()
    assert "Нет активного" in msg.answer.call_args[0][0]


# ── _list_keyboard helper ─────────────────────────────────────────────────────


def test_list_keyboard_filter_buttons_always_present() -> None:
    page = make_list_page([MagicMock()] * 5, page=0, total=5)
    kb = _list_keyboard(page, "ru")
    assert kb is not None
    filter_texts = [b.text for b in kb.inline_keyboard[0]]
    assert any("Все" in t for t in filter_texts)
    assert any("Ссылки" in t for t in filter_texts)
    assert any("Задачи" in t for t in filter_texts)
    assert any("Идеи" in t for t in filter_texts)
    assert any("Заметки" in t for t in filter_texts)


def test_list_keyboard_no_nav_single_page() -> None:
    page = make_list_page([MagicMock()] * 5, page=0, total=5)
    kb = _list_keyboard(page, "ru")
    assert kb is not None
    # Only filter row, no nav row
    assert len(kb.inline_keyboard) == 1


def test_list_keyboard_next_only_first_page() -> None:
    page = make_list_page([MagicMock()] * 10, page=0, total=15)
    kb = _list_keyboard(page, "ru")
    assert kb is not None
    nav_row = kb.inline_keyboard[1]
    texts = [b.text for b in nav_row]
    assert any("Вперёд" in t for t in texts)
    assert not any("Назад" in t for t in texts)


def test_list_keyboard_prev_only_last_page() -> None:
    page = make_list_page([MagicMock()] * 5, page=1, total=15)
    kb = _list_keyboard(page, "ru")
    assert kb is not None
    nav_row = kb.inline_keyboard[1]
    texts = [b.text for b in nav_row]
    assert any("Назад" in t for t in texts)
    assert not any("Вперёд" in t for t in texts)


def test_list_keyboard_both_buttons_middle_page() -> None:
    page = make_list_page([MagicMock()] * 10, page=1, total=30)
    kb = _list_keyboard(page, "ru")
    assert kb is not None
    nav_row = kb.inline_keyboard[1]
    texts = [b.text for b in nav_row]
    assert any("Назад" in t for t in texts)
    assert any("Вперёд" in t for t in texts)


def test_list_keyboard_active_filter_is_highlighted() -> None:
    page = ListPage(items=[], page=0, total=5, item_type=ItemType.link)
    kb = _list_keyboard(page, "ru")
    assert kb is not None
    filter_texts = [b.text for b in kb.inline_keyboard[0]]
    assert any("[" in t and "Ссылки" in t for t in filter_texts)


def test_list_keyboard_nav_buttons_include_type_suffix() -> None:
    page = ListPage(items=[MagicMock()] * 10, page=0, total=15, item_type=ItemType.task)
    kb = _list_keyboard(page, "ru")
    assert kb is not None
    nav_row = kb.inline_keyboard[1]
    assert any("task" in b.callback_data for b in nav_row)


# ── _parse_type_suffix ───────────────────────────────────────────────────────


def test_parse_type_suffix_all() -> None:
    assert _parse_type_suffix("all") is None


def test_parse_type_suffix_valid_type() -> None:
    assert _parse_type_suffix("link") == ItemType.link
    assert _parse_type_suffix("task") == ItemType.task
    assert _parse_type_suffix("idea") == ItemType.idea
    assert _parse_type_suffix("note") == ItemType.note


def test_parse_type_suffix_invalid() -> None:
    assert _parse_type_suffix("invalid") is None


# ── cb_list_filter ───────────────────────────────────────────────────────────


async def test_cb_list_filter_resets_to_page_zero() -> None:
    cb = make_callback("list_filter:link")
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=ListPage(
            items=[make_item("http://example.com", ItemType.link)],
            page=0,
            total=1,
            item_type=ItemType.link,
        )
    )

    await cb_list_filter(cb, list_service=svc, lang="ru")
    svc.list_recent.assert_awaited_once_with(cb.from_user.id, page=0, item_type=ItemType.link)
    cb.message.edit_text.assert_awaited_once()


async def test_cb_list_filter_all_passes_none() -> None:
    cb = make_callback("list_filter:all")
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(return_value=make_list_page([make_item("x")], total=1))

    await cb_list_filter(cb, list_service=svc, lang="ru")
    svc.list_recent.assert_awaited_once_with(cb.from_user.id, page=0, item_type=None)


async def test_cb_list_filter_no_service_is_safe() -> None:
    cb = make_callback("list_filter:link")
    await cb_list_filter(cb, list_service=None, lang="ru")
    cb.message.edit_text.assert_not_awaited()


async def test_cb_list_filter_edit_failure_is_silenced() -> None:
    cb = make_callback("list_filter:note")
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page([make_item("x", ItemType.note)], total=1)
    )
    cb.message.edit_text = AsyncMock(side_effect=Exception("Message not modified"))

    # Should not raise
    await cb_list_filter(cb, list_service=svc, lang="ru")


# ── /reindex ──────────────────────────────────────────────────────────────────


def make_reindex_service(
    *,
    count: int = 0,
    summary: ReindexSummary | None = None,
    summary_exc: Exception | None = None,
) -> MagicMock:
    """Build a ReindexService mock with configurable count + summary outcomes."""
    svc = MagicMock(spec=ReindexService)
    svc.count_unindexed_for_user = AsyncMock(return_value=count)
    if summary_exc is not None:
        svc.reindex_all_for_user = AsyncMock(side_effect=summary_exc)
    else:
        svc.reindex_all_for_user = AsyncMock(
            return_value=summary
            or ReindexSummary(succeeded=0, failed=0, total_found=0, truncated=False)
        )
    return svc


def make_embedding_service(configured: bool = True) -> MagicMock:
    """Build an EmbeddingService mock with the requested ``is_configured`` value."""
    emb = MagicMock(spec=EmbeddingService)
    # ``is_configured`` is a property on the real class — emulate it on the mock.
    type(emb).is_configured = property(lambda self, value=configured: value)
    return emb


def _clear_reindex_lock() -> None:
    """Reset the module-level concurrency lock between tests."""
    commands_module._REINDEX_RUNNING.clear()


async def test_cmd_reindex_no_services_replies_not_configured() -> None:
    _clear_reindex_lock()
    msg = make_message()

    await cmd_reindex(msg, reindex_service=None, embedding_service=None, lang="ru")

    assert "не настроен" in msg.answer.call_args[0][0]


async def test_cmd_reindex_when_voyage_not_configured() -> None:
    _clear_reindex_lock()
    msg = make_message()
    reindex_svc = make_reindex_service(count=5)
    emb = make_embedding_service(configured=False)

    await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="ru")

    assert "не настроен" in msg.answer.call_args[0][0]
    reindex_svc.count_unindexed_for_user.assert_not_awaited()
    reindex_svc.reindex_all_for_user.assert_not_awaited()


async def test_cmd_reindex_when_already_indexed() -> None:
    _clear_reindex_lock()
    msg = make_message()
    reindex_svc = make_reindex_service(count=0)
    emb = make_embedding_service(configured=True)

    await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="ru")

    assert "уже проиндексированы" in msg.answer.call_args[0][0]
    reindex_svc.reindex_all_for_user.assert_not_awaited()


async def test_cmd_reindex_full_success() -> None:
    _clear_reindex_lock()
    msg = make_message()
    reindex_svc = make_reindex_service(
        count=3,
        summary=ReindexSummary(succeeded=3, failed=0, total_found=3, truncated=False),
    )
    emb = make_embedding_service(configured=True)

    await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="ru")

    assert msg.answer.await_count == 2
    first_call = msg.answer.call_args_list[0][0][0]
    assert "Найдено 3" in first_call
    assert "первые 200" not in first_call
    second_call = msg.answer.call_args_list[1][0][0]
    assert "Проиндексировано: 3" in second_call
    assert "Не удалось" not in second_call
    assert "Осталось" not in second_call
    reindex_svc.reindex_all_for_user.assert_awaited_once_with(msg.from_user.id, max_items=200)


async def test_cmd_reindex_partial_success_with_failures() -> None:
    _clear_reindex_lock()
    msg = make_message()
    reindex_svc = make_reindex_service(
        count=5,
        summary=ReindexSummary(succeeded=3, failed=2, total_found=5, truncated=False),
    )
    emb = make_embedding_service(configured=True)

    await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="ru")

    second_call = msg.answer.call_args_list[1][0][0]
    assert "Проиндексировано: 3" in second_call
    assert "Не удалось: 2" in second_call


async def test_cmd_reindex_service_unavailable_first_call() -> None:
    _clear_reindex_lock()
    msg = make_message()
    # All records failed because the very first Voyage AI call returned None.
    reindex_svc = make_reindex_service(
        count=4,
        summary=ReindexSummary(succeeded=0, failed=4, total_found=4, truncated=False),
    )
    emb = make_embedding_service(configured=True)

    await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="ru")

    second_call = msg.answer.call_args_list[1][0][0]
    assert "временно недоступен" in second_call
    assert "Проиндексировано" not in second_call


async def test_cmd_reindex_truncated_suffix_shown_when_more_remain() -> None:
    _clear_reindex_lock()
    msg = make_message()
    reindex_svc = make_reindex_service(
        count=350,
        summary=ReindexSummary(succeeded=200, failed=0, total_found=200, truncated=True),
    )
    emb = make_embedding_service(configured=True)

    await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="ru")

    first_call = msg.answer.call_args_list[0][0][0]
    assert "Найдено 350" in first_call
    assert "первые 200" in first_call
    second_call = msg.answer.call_args_list[1][0][0]
    assert "Проиндексировано: 200" in second_call
    assert "Осталось" in second_call
    assert "/reindex" in second_call


async def test_cmd_reindex_rejects_concurrent_run() -> None:
    _clear_reindex_lock()
    msg = make_message(user_id=42)
    reindex_svc = make_reindex_service(count=10)
    emb = make_embedding_service(configured=True)

    # Simulate the user already having an active reindex run.
    commands_module._REINDEX_RUNNING.add(42)
    try:
        await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="ru")
    finally:
        _clear_reindex_lock()

    assert "уже выполняется" in msg.answer.call_args[0][0]
    reindex_svc.count_unindexed_for_user.assert_not_awaited()
    reindex_svc.reindex_all_for_user.assert_not_awaited()


async def test_cmd_reindex_releases_lock_on_exception() -> None:
    """Even if reindex_service raises, the user is removed from the in-progress set."""
    _clear_reindex_lock()
    msg = make_message(user_id=99)
    reindex_svc = make_reindex_service(count=5, summary_exc=RuntimeError("boom"))
    emb = make_embedding_service(configured=True)

    raised = False
    try:
        await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="ru")
    except RuntimeError:
        raised = True

    assert raised, "the original exception must propagate"
    assert 99 not in commands_module._REINDEX_RUNNING


async def test_cmd_reindex_silent_when_no_user_id() -> None:
    """A defensive no-op when from_user is absent (e.g. anonymous channel post)."""
    _clear_reindex_lock()
    msg = make_message()
    msg.from_user = None
    reindex_svc = make_reindex_service(count=5)
    emb = make_embedding_service(configured=True)

    await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="ru")

    msg.answer.assert_not_awaited()
    reindex_svc.count_unindexed_for_user.assert_not_awaited()


async def test_cmd_reindex_english_full_success() -> None:
    _clear_reindex_lock()
    msg = make_message()
    reindex_svc = make_reindex_service(
        count=2,
        summary=ReindexSummary(succeeded=2, failed=0, total_found=2, truncated=False),
    )
    emb = make_embedding_service(configured=True)

    await cmd_reindex(msg, reindex_service=reindex_svc, embedding_service=emb, lang="en")

    first_call = msg.answer.call_args_list[0][0][0]
    assert "Found 2" in first_call
    second_call = msg.answer.call_args_list[1][0][0]
    assert "Indexed: 2" in second_call
