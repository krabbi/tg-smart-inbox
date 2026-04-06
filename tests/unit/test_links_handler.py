import uuid
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, User

from bot.exceptions import ScrapingError
from bot.handlers.links import (
    _link_keyboard,
    cb_link_remind,
    cb_link_save,
    cb_link_summary,
    handle_link_message,
)
from bot.services.link_service import LinkService, LinkSummary


def make_message(text: str = "https://example.com", user_id: int = 1) -> Message:
    user = MagicMock(spec=User)
    user.id = user_id
    msg = MagicMock(spec=Message)
    msg.from_user = user
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def make_callback(
    data: str, message_text: str = "🔗 Ссылка сохранена:\nhttps://example.com"
) -> CallbackQuery:
    msg = MagicMock()
    msg.text = message_text
    msg.edit_text = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    msg.answer = AsyncMock()
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.message = msg
    cb.answer = AsyncMock()
    return cb


def make_link_service(
    *,
    summary: LinkSummary | None = None,
    scraping_error: bool = False,
) -> LinkService:
    item = MagicMock()
    item.id = uuid.uuid4()

    svc = MagicMock(spec=LinkService)
    svc.save = AsyncMock(return_value=item)

    if scraping_error:
        svc.summarize = AsyncMock(side_effect=ScrapingError("timeout"))
    else:
        svc.summarize = AsyncMock(
            return_value=summary
            or LinkSummary(
                title="Test Title",
                summary="Test summary.",
                url="https://example.com",
                takeaways=["point 1", "point 2"],
            )
        )
    return svc


def test_link_keyboard_returns_inline_markup() -> None:
    kb = _link_keyboard("abc-123")
    assert isinstance(kb, InlineKeyboardMarkup)
    buttons = kb.inline_keyboard[0]
    assert len(buttons) == 3
    assert buttons[0].callback_data == "link:summary:abc-123"
    assert buttons[1].callback_data == "link:save:abc-123"
    assert buttons[2].callback_data == "link:remind:abc-123"


async def test_handle_link_message_saves_and_replies() -> None:
    message = make_message()
    svc = make_link_service()
    await handle_link_message(message, "https://example.com", svc)
    svc.save.assert_awaited_once_with("https://example.com", 1)
    message.answer.assert_awaited_once()
    _, kwargs = message.answer.call_args
    assert "reply_markup" in kwargs


async def test_cb_link_summary_edits_message() -> None:
    item_id = str(uuid.uuid4())
    cb = make_callback(f"link:summary:{item_id}", "🔗 Saved:\nhttps://example.com")
    svc = make_link_service()
    await cb_link_summary(cb, svc)
    cb.answer.assert_awaited_once()
    cb.message.edit_text.assert_awaited_once()
    edited = cb.message.edit_text.call_args[0][0]
    assert "Test Title" in edited
    assert "Test summary." in edited


async def test_cb_link_summary_with_no_takeaways() -> None:
    item_id = str(uuid.uuid4())
    cb = make_callback(f"link:summary:{item_id}", "🔗 Saved:\nhttps://example.com")
    summary = LinkSummary(title="T", summary="S", url="https://x.com", takeaways=[])
    svc = make_link_service(summary=summary)
    await cb_link_summary(cb, svc)
    cb.message.edit_text.assert_awaited_once()


async def test_cb_link_summary_scraping_error_shows_error_message() -> None:
    item_id = str(uuid.uuid4())
    cb = make_callback(f"link:summary:{item_id}")
    svc = make_link_service(scraping_error=True)
    await cb_link_summary(cb, svc)
    cb.message.edit_text.assert_awaited_once()
    assert "❌" in cb.message.edit_text.call_args[0][0]


async def test_cb_link_save_removes_keyboard() -> None:
    cb = make_callback("link:save:abc")
    await cb_link_save(cb)
    cb.answer.assert_awaited_once()
    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


async def test_cb_link_remind_answers() -> None:
    from aiogram.fsm.context import FSMContext

    cb = make_callback("link:remind:abc")
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await cb_link_remind(cb, state=state)

    cb.answer.assert_awaited_once()
