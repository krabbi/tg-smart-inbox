"""Tests for link button callbacks — summary, save, and remind."""

from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.handlers.links import cb_link_remind, cb_link_save, cb_link_summary
from bot.services.link_service import LinkService, LinkSummary


def make_callback(
    data: str, message_text: str = "🔗 Ссылка сохранена:\nhttps://example.com"
) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = 1
    cb.message = MagicMock(spec=Message)
    cb.message.text = message_text
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


# ── cb_link_summary ───────────────────────────────────────────────────────────


async def test_cb_link_summary_edits_message_with_summary() -> None:
    cb = make_callback("link:summary:some-uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(
        return_value=LinkSummary(
            title="Example Title",
            summary="A brief summary.",
            url="https://example.com",
            takeaways=["Point 1", "Point 2"],
        )
    )

    await cb_link_summary(cb, link_service=svc)
    cb.message.edit_text.assert_awaited_once()
    content = cb.message.edit_text.call_args[0][0]
    assert "Example Title" in content
    assert "Point 1" in content


async def test_cb_link_summary_answers_callback() -> None:
    cb = make_callback("link:summary:uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(
        return_value=LinkSummary(title="T", summary="S", url="", takeaways=[])
    )

    await cb_link_summary(cb, link_service=svc)
    cb.answer.assert_awaited()


async def test_cb_link_summary_scraping_error_edits_error_message() -> None:
    from bot.exceptions import ScrapingError

    cb = make_callback("link:summary:uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(side_effect=ScrapingError("failed"))

    await cb_link_summary(cb, link_service=svc)
    cb.message.edit_text.assert_awaited_once()
    assert "❌" in cb.message.edit_text.call_args[0][0]


# ── cb_link_save ──────────────────────────────────────────────────────────────


async def test_cb_link_save_answers_and_removes_keyboard() -> None:
    cb = make_callback("link:save:uuid")

    await cb_link_save(cb)
    cb.answer.assert_awaited_once()
    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


# ── cb_link_remind ────────────────────────────────────────────────────────────


async def test_cb_link_remind_triggers_ask_reminder() -> None:
    cb = make_callback("link:remind:some-item-id")
    state = MagicMock(spec=FSMContext)

    with patch("bot.handlers.reminders.ask_reminder", new=AsyncMock()) as mock_ask:
        await cb_link_remind(cb, state=state)

    mock_ask.assert_awaited_once()
    call_kwargs = mock_ask.call_args[1]
    assert call_kwargs["item_id"] == "some-item-id"
    assert call_kwargs["task_text"] == "https://example.com"
    assert call_kwargs["state"] is state


async def test_cb_link_remind_removes_keyboard_before_fsm() -> None:
    cb = make_callback("link:remind:uuid")
    state = MagicMock(spec=FSMContext)

    with patch("bot.handlers.reminders.ask_reminder", new=AsyncMock()):
        await cb_link_remind(cb, state=state)

    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


async def test_cb_link_remind_answers_callback() -> None:
    cb = make_callback("link:remind:uuid")
    state = MagicMock(spec=FSMContext)

    with patch("bot.handlers.reminders.ask_reminder", new=AsyncMock()):
        await cb_link_remind(cb, state=state)

    cb.answer.assert_awaited_once()


async def test_cb_link_remind_no_message_returns_early() -> None:
    cb = make_callback("link:remind:uuid")
    cb.message = None
    state = MagicMock(spec=FSMContext)

    with patch("bot.handlers.reminders.ask_reminder", new=AsyncMock()) as mock_ask:
        await cb_link_remind(cb, state=state)

    mock_ask.assert_not_awaited()
