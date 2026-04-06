"""Tests for /list, /search, /reminders command handlers."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from aiogram.filters import CommandObject
from aiogram.types import CallbackQuery, Message, User

from bot.handlers.commands import (
    _list_keyboard,
    cb_cancel_reminder,
    cb_list_page,
    cmd_list,
    cmd_reminders,
    cmd_search,
)
from bot.models.item import Item, ItemType
from bot.models.reminder import Reminder
from bot.services.list_service import ListPage, ListService
from bot.services.reminder_service import ReminderService


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


def make_item(content: str, item_type: ItemType = ItemType.note) -> MagicMock:
    item = MagicMock(spec=Item)
    item.content = content
    item.type = item_type
    item.created_at = MagicMock()
    item.created_at.strftime = MagicMock(return_value="01.01.2026")
    return item


def make_reminder(content: str, reminder_id: uuid.UUID | None = None) -> MagicMock:
    r = MagicMock(spec=Reminder)
    r.id = reminder_id or uuid.uuid4()
    r.item = MagicMock()
    r.item.content = content
    r.remind_at = MagicMock()
    r.remind_at.strftime = MagicMock(return_value="05.04.2026 10:00")
    return r


def make_list_page(items: list, page: int = 0, total: int | None = None) -> ListPage:
    return ListPage(items=items, page=page, total=total if total is not None else len(items))


# ── /list ─────────────────────────────────────────────────────────────────────


async def test_cmd_list_no_service_gives_stub() -> None:
    msg = make_message()
    await cmd_list(msg, list_service=None)
    assert "скоро" in msg.answer.call_args[0][0]


async def test_cmd_list_empty_gives_friendly_message() -> None:
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(return_value=make_list_page([], total=0))

    await cmd_list(msg, list_service=svc)
    assert "ничего не сохранено" in msg.answer.call_args[0][0].lower()


async def test_cmd_list_shows_items() -> None:
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page(
            [make_item("cool link", ItemType.link), make_item("buy milk", ItemType.task)], total=2
        )
    )

    await cmd_list(msg, list_service=svc)
    reply = msg.answer.call_args[0][0]
    assert "cool link" in reply
    assert "buy milk" in reply
    assert "🔗" in reply
    assert "✅" in reply


async def test_cmd_list_no_pagination_for_single_page() -> None:
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page([make_item("x") for _ in range(3)], total=3)
    )

    await cmd_list(msg, list_service=svc)
    _, kwargs = msg.answer.call_args
    assert kwargs.get("reply_markup") is None


async def test_cmd_list_shows_next_button_when_more() -> None:
    msg = make_message()
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page([make_item(f"item {i}") for i in range(10)], total=15)
    )

    await cmd_list(msg, list_service=svc)
    _, kwargs = msg.answer.call_args
    kb = kwargs.get("reply_markup")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)


# ── cb_list_page ──────────────────────────────────────────────────────────────


async def test_cb_list_page_edits_message() -> None:
    cb = make_callback("list_page:1")
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(
        return_value=make_list_page([make_item("item a")], page=1, total=15)
    )

    await cb_list_page(cb, list_service=svc)
    cb.message.edit_text.assert_awaited_once()
    svc.list_recent.assert_awaited_once_with(cb.from_user.id, page=1)


async def test_cb_list_page_invalid_data_is_ignored() -> None:
    cb = make_callback("list_page:notanint")
    svc = MagicMock(spec=ListService)

    await cb_list_page(cb, list_service=svc)
    svc.list_recent.assert_not_awaited()


async def test_cb_list_page_edit_failure_is_silenced() -> None:
    cb = make_callback("list_page:0")
    svc = MagicMock(spec=ListService)
    svc.list_recent = AsyncMock(return_value=make_list_page([make_item("x")], page=0, total=5))
    cb.message.edit_text = AsyncMock(side_effect=Exception("Message not modified"))

    # Should not raise
    await cb_list_page(cb, list_service=svc)


# ── /search ───────────────────────────────────────────────────────────────────


async def test_cmd_search_no_query_shows_hint() -> None:
    msg = make_message()
    cmd_obj = MagicMock(spec=CommandObject)
    cmd_obj.args = None
    svc = MagicMock(spec=ListService)

    await cmd_search(msg, command=cmd_obj, list_service=svc)
    assert "/search" in msg.answer.call_args[0][0]


async def test_cmd_search_no_results() -> None:
    msg = make_message()
    cmd_obj = MagicMock(spec=CommandObject)
    cmd_obj.args = "unicorn"
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[])

    await cmd_search(msg, command=cmd_obj, list_service=svc)
    assert "Ничего" in msg.answer.call_args[0][0]


async def test_cmd_search_shows_results() -> None:
    msg = make_message()
    cmd_obj = MagicMock(spec=CommandObject)
    cmd_obj.args = "coffee"
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[make_item("coffee shop receipt", ItemType.link)])

    await cmd_search(msg, command=cmd_obj, list_service=svc)
    assert "coffee shop receipt" in msg.answer.call_args[0][0]


async def test_cmd_search_shows_limit_note_when_full_page() -> None:
    msg = make_message()
    cmd_obj = MagicMock(spec=CommandObject)
    cmd_obj.args = "item"
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[make_item(f"item {i}") for i in range(10)])

    await cmd_search(msg, command=cmd_obj, list_service=svc)
    assert "10" in msg.answer.call_args[0][0]


async def test_cmd_search_no_service_gives_stub() -> None:
    msg = make_message()
    cmd_obj = MagicMock(spec=CommandObject)
    cmd_obj.args = "query"
    await cmd_search(msg, command=cmd_obj, list_service=None)
    assert "скоро" in msg.answer.call_args[0][0]


# ── /reminders ────────────────────────────────────────────────────────────────


async def test_cmd_reminders_no_service_gives_stub() -> None:
    msg = make_message()
    await cmd_reminders(msg, reminder_service=None)
    assert "скоро" in msg.answer.call_args[0][0]


async def test_cmd_reminders_empty() -> None:
    msg = make_message()
    svc = MagicMock(spec=ReminderService)
    svc.get_upcoming = AsyncMock(return_value=[])

    await cmd_reminders(msg, reminder_service=svc)
    assert "нет" in msg.answer.call_args[0][0].lower()


async def test_cmd_reminders_shows_list() -> None:
    msg = make_message()
    svc = MagicMock(spec=ReminderService)
    svc.get_upcoming = AsyncMock(
        return_value=[make_reminder("buy milk"), make_reminder("call dentist")]
    )

    await cmd_reminders(msg, reminder_service=svc)
    assert msg.answer.await_count == 2
    calls = [c[0][0] for c in msg.answer.call_args_list]
    assert any("buy milk" in c for c in calls)
    assert any("call dentist" in c for c in calls)


# ── cb_cancel_reminder ────────────────────────────────────────────────────────


async def test_cb_cancel_reminder_cancels_and_edits() -> None:
    rid = uuid.uuid4()
    cb = make_callback(f"cancel_reminder:{rid}")
    svc = MagicMock(spec=ReminderService)
    svc.cancel_for_user = AsyncMock(return_value=True)

    await cb_cancel_reminder(cb, reminder_service=svc)
    svc.cancel_for_user.assert_awaited_once_with(rid, cb.from_user.id)
    cb.message.edit_text.assert_awaited_once()
    assert "отменено" in cb.message.edit_text.call_args[0][0].lower()


async def test_cb_cancel_reminder_not_owned_does_not_edit() -> None:
    rid = uuid.uuid4()
    cb = make_callback(f"cancel_reminder:{rid}")
    svc = MagicMock(spec=ReminderService)
    svc.cancel_for_user = AsyncMock(return_value=False)

    await cb_cancel_reminder(cb, reminder_service=svc)
    cb.message.edit_text.assert_not_awaited()


async def test_cb_cancel_reminder_invalid_uuid_is_safe() -> None:
    cb = make_callback("cancel_reminder:not-a-uuid")
    svc = MagicMock(spec=ReminderService)

    await cb_cancel_reminder(cb, reminder_service=svc)
    svc.cancel_for_user.assert_not_awaited()


async def test_cb_cancel_reminder_edit_failure_is_silenced() -> None:
    rid = uuid.uuid4()
    cb = make_callback(f"cancel_reminder:{rid}")
    svc = MagicMock(spec=ReminderService)
    svc.cancel_for_user = AsyncMock(return_value=True)
    cb.message.edit_text = AsyncMock(side_effect=Exception("Message deleted"))

    # Should not raise
    await cb_cancel_reminder(cb, reminder_service=svc)


# ── _list_keyboard helper ─────────────────────────────────────────────────────


def test_list_keyboard_no_buttons_single_page() -> None:
    page = make_list_page([MagicMock()] * 5, page=0, total=5)
    assert _list_keyboard(page) is None


def test_list_keyboard_next_only_first_page() -> None:
    page = make_list_page([MagicMock()] * 10, page=0, total=15)
    kb = _list_keyboard(page)
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)
    assert not any("Назад" in t for t in texts)


def test_list_keyboard_prev_only_last_page() -> None:
    page = make_list_page([MagicMock()] * 5, page=1, total=15)
    kb = _list_keyboard(page)
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Назад" in t for t in texts)
    assert not any("Вперёд" in t for t in texts)


def test_list_keyboard_both_buttons_middle_page() -> None:
    page = make_list_page([MagicMock()] * 10, page=1, total=30)
    kb = _list_keyboard(page)
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Назад" in t for t in texts)
    assert any("Вперёд" in t for t in texts)
