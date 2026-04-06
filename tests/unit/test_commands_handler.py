"""Tests for /list, /search, /reminders command handlers."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from aiogram.filters import CommandObject
from aiogram.types import Message, User

from bot.handlers.commands import (
    _list_keyboard,
    cmd_list,
    cmd_reminders,
    cmd_search,
)
from bot.models.item import Item, ItemType
from bot.models.reminder import Reminder
from bot.repositories.item_repository import ItemRepository
from bot.repositories.reminder_repository import ReminderRepository


def make_message(user_id: int = 1) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    return msg


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


# ── /list ─────────────────────────────────────────────────────────────────────


async def test_cmd_list_no_service_gives_stub() -> None:
    msg = make_message()
    await cmd_list(msg, item_repo=None)
    msg.answer.assert_awaited_once()
    assert "скоро" in msg.answer.call_args[0][0]


async def test_cmd_list_empty_gives_friendly_message() -> None:
    msg = make_message()
    repo = MagicMock(spec=ItemRepository)
    repo.count_by_user = AsyncMock(return_value=0)

    await cmd_list(msg, item_repo=repo)
    msg.answer.assert_awaited_once()
    assert "ничего не сохранено" in msg.answer.call_args[0][0].lower()


async def test_cmd_list_shows_items() -> None:
    msg = make_message()
    repo = MagicMock(spec=ItemRepository)
    repo.count_by_user = AsyncMock(return_value=2)
    repo.get_recent = AsyncMock(
        return_value=[make_item("cool link", ItemType.link), make_item("buy milk", ItemType.task)]
    )

    await cmd_list(msg, item_repo=repo)
    reply = msg.answer.call_args[0][0]
    assert "cool link" in reply
    assert "buy milk" in reply
    assert "🔗" in reply
    assert "✅" in reply


async def test_cmd_list_no_pagination_for_single_page() -> None:
    msg = make_message()
    repo = MagicMock(spec=ItemRepository)
    repo.count_by_user = AsyncMock(return_value=3)
    repo.get_recent = AsyncMock(return_value=[make_item("x") for _ in range(3)])

    await cmd_list(msg, item_repo=repo)
    _, kwargs = msg.answer.call_args
    assert kwargs.get("reply_markup") is None


async def test_cmd_list_shows_next_button_when_more() -> None:
    msg = make_message()
    repo = MagicMock(spec=ItemRepository)
    repo.count_by_user = AsyncMock(return_value=15)
    repo.get_recent = AsyncMock(return_value=[make_item(f"item {i}") for i in range(10)])

    await cmd_list(msg, item_repo=repo)
    _, kwargs = msg.answer.call_args
    kb = kwargs.get("reply_markup")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)


# ── /search ───────────────────────────────────────────────────────────────────


async def test_cmd_search_no_query_shows_hint() -> None:
    msg = make_message()
    cmd_obj = MagicMock(spec=CommandObject)
    cmd_obj.args = None
    repo = MagicMock(spec=ItemRepository)

    await cmd_search(msg, command=cmd_obj, item_repo=repo)
    reply = msg.answer.call_args[0][0]
    assert "/search" in reply


async def test_cmd_search_no_results() -> None:
    msg = make_message()
    cmd_obj = MagicMock(spec=CommandObject)
    cmd_obj.args = "unicorn"
    repo = MagicMock(spec=ItemRepository)
    repo.search = AsyncMock(return_value=[])

    await cmd_search(msg, command=cmd_obj, item_repo=repo)
    reply = msg.answer.call_args[0][0]
    assert "не найдено" in reply.lower() or "Ничего" in reply


async def test_cmd_search_shows_results() -> None:
    msg = make_message()
    cmd_obj = MagicMock(spec=CommandObject)
    cmd_obj.args = "coffee"
    repo = MagicMock(spec=ItemRepository)
    repo.search = AsyncMock(return_value=[make_item("coffee shop receipt", ItemType.link)])

    await cmd_search(msg, command=cmd_obj, item_repo=repo)
    reply = msg.answer.call_args[0][0]
    assert "coffee shop receipt" in reply


async def test_cmd_search_no_service_gives_stub() -> None:
    msg = make_message()
    cmd_obj = MagicMock(spec=CommandObject)
    cmd_obj.args = "query"
    await cmd_search(msg, command=cmd_obj, item_repo=None)
    assert "скоро" in msg.answer.call_args[0][0]


# ── /reminders ────────────────────────────────────────────────────────────────


async def test_cmd_reminders_no_service_gives_stub() -> None:
    msg = make_message()
    await cmd_reminders(msg, reminder_repo=None)
    assert "скоро" in msg.answer.call_args[0][0]


async def test_cmd_reminders_empty() -> None:
    msg = make_message()
    repo = MagicMock(spec=ReminderRepository)
    repo.get_upcoming = AsyncMock(return_value=[])

    await cmd_reminders(msg, reminder_repo=repo)
    assert "нет" in msg.answer.call_args[0][0].lower()


async def test_cmd_reminders_shows_list() -> None:
    msg = make_message()
    repo = MagicMock(spec=ReminderRepository)
    repo.get_upcoming = AsyncMock(
        return_value=[make_reminder("buy milk"), make_reminder("call dentist")]
    )

    await cmd_reminders(msg, reminder_repo=repo)
    assert msg.answer.await_count == 2
    calls = [c[0][0] for c in msg.answer.call_args_list]
    assert any("buy milk" in c for c in calls)
    assert any("call dentist" in c for c in calls)


# ── _list_keyboard helper ─────────────────────────────────────────────────────


def test_list_keyboard_no_buttons_single_page() -> None:
    assert _list_keyboard(page=0, total=5) is None


def test_list_keyboard_next_only_first_page() -> None:
    kb = _list_keyboard(page=0, total=15)
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)
    assert not any("Назад" in t for t in texts)


def test_list_keyboard_prev_only_last_page() -> None:
    kb = _list_keyboard(page=1, total=15)
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Назад" in t for t in texts)
    assert not any("Вперёд" in t for t in texts)


def test_list_keyboard_both_buttons_middle_page() -> None:
    kb = _list_keyboard(page=1, total=30)
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Назад" in t for t in texts)
    assert any("Вперёд" in t for t in texts)
