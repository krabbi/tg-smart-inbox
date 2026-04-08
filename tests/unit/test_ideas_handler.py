from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery, Message

from bot.handlers.ideas import (
    _ideas_keyboard,
    cb_ideas_page,
    handle_ideas_command,
)
from bot.models.idea import Idea, IdeaComplexity, IdeaEffort
from bot.models.item import Item
from bot.services.idea_service import IdeaService, IdeasPage


def make_message(user_id: int = 1) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    return msg


def make_callback(data: str, user_id: int = 1) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    return cb


def make_idea_row(
    content: str,
    tags: list[str],
    complexity: IdeaComplexity | None = None,
    effort: IdeaEffort | None = None,
) -> tuple[MagicMock, MagicMock]:
    item = MagicMock(spec=Item)
    item.content = content
    item.created_at = MagicMock()
    item.created_at.strftime = MagicMock(return_value="01.01.2026")
    idea = MagicMock(spec=Idea)
    idea.tags = tags
    idea.complexity = complexity
    idea.effort = effort
    return item, idea


async def test_handle_ideas_no_service_sends_stub() -> None:
    msg = make_message()
    await handle_ideas_command(msg, idea_service=None)
    msg.answer.assert_awaited_once()
    assert "скоро" in msg.answer.call_args[0][0]


async def test_handle_ideas_empty_list() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=[], page=0, total=0))

    await handle_ideas_command(msg, idea_service=svc)
    msg.answer.assert_awaited_once()
    assert (
        "нет идей" in msg.answer.call_args[0][0].lower()
        or "пока" in msg.answer.call_args[0][0].lower()
    )


async def test_handle_ideas_shows_list() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    rows = [
        make_idea_row("Build a Telegram bot", ["bot", "telegram"]),
        make_idea_row("Write a novel", ["writing"]),
    ]
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=rows, page=0, total=2))

    await handle_ideas_command(msg, idea_service=svc)
    reply = msg.answer.call_args[0][0]
    assert "Telegram bot" in reply
    assert "#bot" in reply
    assert "novel" in reply


async def test_handle_ideas_truncates_long_content() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    long_text = "a" * 200
    rows = [make_idea_row(long_text, [])]
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=rows, page=0, total=1))

    await handle_ideas_command(msg, idea_service=svc)
    reply = msg.answer.call_args[0][0]
    assert "…" in reply


async def test_handle_ideas_shows_complexity_and_effort() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    rows = [
        make_idea_row(
            "Build a helicopter",
            [],
            complexity=IdeaComplexity.complex,
            effort=IdeaEffort.longterm,
        )
    ]
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=rows, page=0, total=1))

    await handle_ideas_command(msg, idea_service=svc)
    reply = msg.answer.call_args[0][0]
    assert "сложная" in reply
    assert "долгосрочно" in reply


async def test_handle_ideas_shows_total_count() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    rows = [make_idea_row(f"idea {i}", []) for i in range(10)]
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=rows, page=0, total=15))

    await handle_ideas_command(msg, idea_service=svc)
    reply = msg.answer.call_args[0][0]
    assert "15" in reply


async def test_handle_ideas_no_pagination_for_single_page() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    rows = [make_idea_row("idea", []) for _ in range(3)]
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=rows, page=0, total=3))

    await handle_ideas_command(msg, idea_service=svc)
    _, kwargs = msg.answer.call_args
    assert kwargs.get("reply_markup") is None


async def test_handle_ideas_shows_next_button_when_more() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    rows = [make_idea_row(f"idea {i}", []) for i in range(10)]
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=rows, page=0, total=15))

    await handle_ideas_command(msg, idea_service=svc)
    _, kwargs = msg.answer.call_args
    kb = kwargs.get("reply_markup")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)


# ── cb_ideas_page ────────────────────────────────────────────────────────────


async def test_cb_ideas_page_edits_message() -> None:
    cb = make_callback("ideas_page:1")
    svc = MagicMock(spec=IdeaService)
    rows = [make_idea_row("idea a", [])]
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=rows, page=1, total=15))

    await cb_ideas_page(cb, idea_service=svc)
    cb.message.edit_text.assert_awaited_once()
    svc.get_page.assert_awaited_once_with(cb.from_user.id, page=1)


async def test_cb_ideas_page_invalid_data_is_ignored() -> None:
    cb = make_callback("ideas_page:notanint")
    svc = MagicMock(spec=IdeaService)

    await cb_ideas_page(cb, idea_service=svc)
    svc.get_page.assert_not_awaited()


async def test_cb_ideas_page_edit_failure_is_silenced() -> None:
    cb = make_callback("ideas_page:0")
    svc = MagicMock(spec=IdeaService)
    rows = [make_idea_row("x", [])]
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=rows, page=0, total=5))
    cb.message.edit_text = AsyncMock(side_effect=Exception("Message not modified"))

    # Should not raise
    await cb_ideas_page(cb, idea_service=svc)


async def test_cb_ideas_page_no_service_is_safe() -> None:
    cb = make_callback("ideas_page:0")
    await cb_ideas_page(cb, idea_service=None)
    cb.message.edit_text.assert_not_awaited()


# ── _ideas_keyboard helper ───────────────────────────────────────────────────


def test_ideas_keyboard_no_buttons_single_page() -> None:
    page = IdeasPage(rows=[], page=0, total=5)
    assert _ideas_keyboard(page) is None


def test_ideas_keyboard_next_only_first_page() -> None:
    page = IdeasPage(rows=[], page=0, total=15)
    kb = _ideas_keyboard(page)
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)
    assert not any("Назад" in t for t in texts)


def test_ideas_keyboard_prev_only_last_page() -> None:
    page = IdeasPage(rows=[], page=1, total=15)
    kb = _ideas_keyboard(page)
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Назад" in t for t in texts)
    assert not any("Вперёд" in t for t in texts)


def test_ideas_keyboard_both_buttons_middle_page() -> None:
    page = IdeasPage(rows=[], page=1, total=30)
    kb = _ideas_keyboard(page)
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Назад" in t for t in texts)
    assert any("Вперёд" in t for t in texts)


async def test_handle_ideas_page_numbering_on_second_page() -> None:
    svc = MagicMock(spec=IdeaService)
    rows = [make_idea_row(f"idea {i}", []) for i in range(5)]
    svc.get_page = AsyncMock(return_value=IdeasPage(rows=rows, page=1, total=15))

    cb = make_callback("ideas_page:1")
    await cb_ideas_page(cb, idea_service=svc)

    reply = cb.message.edit_text.call_args[0][0]
    # Items on page 2 should start numbering from 11
    assert "11." in reply
