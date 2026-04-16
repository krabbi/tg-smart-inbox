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
from bot.services.link_service import LinkService, LinkSummary, SavedLink


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
    indexed: bool = True,
) -> LinkService:
    item = MagicMock()
    item.id = uuid.uuid4()

    svc = MagicMock(spec=LinkService)
    svc.save = AsyncMock(return_value=SavedLink(item=item, indexed=indexed))

    if scraping_error:
        svc.summarize = AsyncMock(side_effect=ScrapingError("timeout"))
    else:
        svc.summarize = AsyncMock(
            return_value=summary
            or LinkSummary(
                title="Test Title",
                body="Test summary.\n• point 1\n• point 2",
                url="https://example.com",
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
    call_kwargs = message.answer.call_args[1]
    assert "reply_markup" in call_kwargs


async def test_handle_link_message_warns_when_not_indexed() -> None:
    """When embedding fails, the handler warns the user after the save confirmation."""
    message = make_message()
    svc = make_link_service(indexed=False)
    await handle_link_message(message, "https://example.com", svc)

    replies = [c[0][0] for c in message.answer.call_args_list]
    assert any("Ссылка сохранена" in r for r in replies)
    assert any("Умный поиск временно недоступен" in r for r in replies)


async def test_cb_link_summary_edits_message() -> None:
    item_id = str(uuid.uuid4())
    cb = make_callback(f"link:summary:{item_id}", "🔗 Saved:\nhttps://example.com")
    svc = make_link_service()
    await cb_link_summary(cb, svc)
    cb.answer.assert_awaited_once()
    # Two edit_text calls: loading state + final summary
    assert cb.message.edit_text.await_count == 2
    edited = cb.message.edit_text.call_args_list[1][0][0]
    assert "Test Title" in edited
    assert "Test summary." in edited


async def test_cb_link_summary_uses_html_parse_mode() -> None:
    """Formatted summary must be sent with parse_mode=HTML, never as raw JSON."""
    item_id = str(uuid.uuid4())
    cb = make_callback(f"link:summary:{item_id}", "🔗 Saved:\nhttps://example.com")
    svc = make_link_service()
    await cb_link_summary(cb, svc)
    # Final summary is the second edit_text call
    _, kwargs = cb.message.edit_text.call_args_list[1]
    assert kwargs.get("parse_mode") == "HTML"
    text = cb.message.edit_text.call_args_list[1][0][0]
    # Must not contain raw JSON curly braces at top level
    assert not text.startswith("{")
    assert "<b>" in text


async def test_cb_link_summary_with_body_only() -> None:
    item_id = str(uuid.uuid4())
    cb = make_callback(f"link:summary:{item_id}", "🔗 Saved:\nhttps://example.com")
    summary = LinkSummary(title="T", body="Short body.", url="https://x.com")
    svc = make_link_service(summary=summary)
    await cb_link_summary(cb, svc)
    # Two edit_text calls: loading state + final summary
    assert cb.message.edit_text.await_count == 2


async def test_cb_link_summary_scraping_error_shows_error_message() -> None:
    item_id = str(uuid.uuid4())
    cb = make_callback(f"link:summary:{item_id}")
    svc = make_link_service(scraping_error=True)
    await cb_link_summary(cb, svc)
    # Two edit_text calls: loading state + error message
    assert cb.message.edit_text.await_count == 2
    assert "❌" in cb.message.edit_text.call_args_list[1][0][0]


async def test_cb_link_save_appends_confirmation_text() -> None:
    cb = make_callback("link:save:abc")
    cb.message.html_text = "🔗 Ссылка сохранена:\nhttps://example.com"
    await cb_link_save(cb)
    cb.answer.assert_awaited_once()
    cb.message.edit_text.assert_awaited_once()
    text = cb.message.edit_text.call_args[0][0]
    assert "Сохранено" in text
    assert "https://example.com" in text


async def test_cb_link_remind_answers() -> None:
    from aiogram.fsm.context import FSMContext

    cb = make_callback("link:remind:abc")
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await cb_link_remind(cb, state=state)

    cb.answer.assert_awaited_once()
