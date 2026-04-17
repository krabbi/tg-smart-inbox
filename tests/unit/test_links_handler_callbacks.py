"""Tests for link button callbacks — summary, save, remind, and retry."""

from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions import ScrapingError
from bot.handlers.links import (
    _extract_url_from_status_message,
    cb_link_close,
    cb_link_remind,
    cb_link_retry,
    cb_link_save,
    cb_link_summary,
)
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


async def test_cb_link_summary_shows_loading_state_immediately() -> None:
    """After tapping Саммари, message should show loading indicator with URL."""
    cb = make_callback("link:summary:some-uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(
        return_value=LinkSummary(title="T", body="B", url="https://example.com")
    )

    await cb_link_summary(cb, link_service=svc)

    # First edit_text call is loading state
    first_call = cb.message.edit_text.call_args_list[0]
    text = first_call[0][0]
    assert "⏳ Загружаю саммари..." in text
    assert "https://example.com" in text
    # Loading state has no keyboard
    assert first_call[1].get("reply_markup") is None


async def test_cb_link_summary_edits_message_with_summary() -> None:
    cb = make_callback("link:summary:some-uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(
        return_value=LinkSummary(
            title="Example Title",
            body="A brief summary.\n• Point 1\n• Point 2",
            url="https://example.com",
        )
    )

    await cb_link_summary(cb, link_service=svc)

    # Second edit_text call is the final summary
    final_call = cb.message.edit_text.call_args_list[1]
    content = final_call[0][0]
    assert "Example Title" in content
    assert "Point 1" in content


async def test_cb_link_summary_preserves_url_in_final_message() -> None:
    """Final summary message must contain the original URL."""
    cb = make_callback("link:summary:some-uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(
        return_value=LinkSummary(title="T", body="B", url="https://example.com")
    )

    await cb_link_summary(cb, link_service=svc)

    final_call = cb.message.edit_text.call_args_list[1]
    content = final_call[0][0]
    assert "https://example.com" in content


async def test_cb_link_summary_shows_save_button_after_summary() -> None:
    """After summary loads, a save button should be shown."""
    cb = make_callback("link:summary:some-uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(
        return_value=LinkSummary(title="T", body="B", url="https://example.com")
    )

    await cb_link_summary(cb, link_service=svc)

    final_call = cb.message.edit_text.call_args_list[1]
    keyboard = final_call[1].get("reply_markup")
    assert keyboard is not None
    button_text = keyboard.inline_keyboard[0][0].text
    assert "Сохранить" in button_text


async def test_cb_link_summary_shows_all_three_action_buttons() -> None:
    """After summary, user should see Save / Remind / Close buttons with correct callback data."""
    cb = make_callback("link:summary:item-xyz")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(
        return_value=LinkSummary(title="T", body="B", url="https://example.com")
    )

    await cb_link_summary(cb, link_service=svc)

    final_call = cb.message.edit_text.call_args_list[1]
    keyboard = final_call[1].get("reply_markup")
    assert keyboard is not None
    row = keyboard.inline_keyboard[0]
    assert len(row) == 3
    assert "Сохранить" in row[0].text
    assert "Напомнить" in row[1].text
    assert "Закрыть" in row[2].text
    assert row[0].callback_data == "link:save:item-xyz"
    assert row[1].callback_data == "link:remind:item-xyz"
    assert row[2].callback_data == "link:close:item-xyz"


async def test_cb_link_summary_answers_callback() -> None:
    cb = make_callback("link:summary:uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(return_value=LinkSummary(title="T", body="S", url=""))

    await cb_link_summary(cb, link_service=svc)
    cb.answer.assert_awaited()


async def test_cb_link_summary_scraping_error_shows_retry_button() -> None:
    cb = make_callback("link:summary:uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(side_effect=ScrapingError("failed"))

    await cb_link_summary(cb, link_service=svc)

    # Second edit_text call is the error state
    error_call = cb.message.edit_text.call_args_list[1]
    text = error_call[0][0]
    assert "❌" in text
    assert "https://example.com" in text
    keyboard = error_call[1].get("reply_markup")
    assert keyboard is not None
    button_text = keyboard.inline_keyboard[0][0].text
    assert "Попробовать снова" in button_text


async def test_cb_link_summary_scraping_error_preserves_url() -> None:
    cb = make_callback("link:summary:uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(side_effect=ScrapingError("failed"))

    await cb_link_summary(cb, link_service=svc)

    error_call = cb.message.edit_text.call_args_list[1]
    assert "https://example.com" in error_call[0][0]


async def test_cb_link_summary_unexpected_error_shows_retry_button() -> None:
    """Non-ScrapingError exceptions (e.g. network, Claude API) must not leak."""
    cb = make_callback("link:summary:uuid")
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(side_effect=Exception("Claude API exploded"))

    await cb_link_summary(cb, link_service=svc)

    error_call = cb.message.edit_text.call_args_list[1]
    text = error_call[0][0]
    assert "❌" in text
    keyboard = error_call[1].get("reply_markup")
    assert keyboard is not None
    assert "Попробовать снова" in keyboard.inline_keyboard[0][0].text


# ── cb_link_retry ────────────────────────────────────────────────────────────


async def test_cb_link_retry_triggers_summarize_flow() -> None:
    """Retry button should re-run the summarize flow."""
    import uuid

    item_id = uuid.uuid4()
    cb = make_callback(
        f"link:retry:{item_id}",
        message_text="🔗 https://example.com\n\n❌ Не удалось загрузить страницу.",
    )
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(
        return_value=LinkSummary(title="T", body="B", url="https://example.com")
    )

    await cb_link_retry(cb, link_service=svc)

    svc.summarize.assert_awaited_once_with("https://example.com", item_id=item_id)
    # Should show loading then final result (2 edit_text calls)
    assert cb.message.edit_text.await_count == 2


async def test_cb_link_retry_answers_callback() -> None:
    cb = make_callback(
        "link:retry:uuid",
        message_text="🔗 https://example.com\n\n❌ Не удалось загрузить страницу.",
    )
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(return_value=LinkSummary(title="T", body="B", url=""))

    await cb_link_retry(cb, link_service=svc)
    cb.answer.assert_awaited()


async def test_cb_link_retry_error_shows_retry_again() -> None:
    """If retry also fails, show retry button again."""
    cb = make_callback(
        "link:retry:uuid",
        message_text="🔗 https://example.com\n\n❌ Не удалось загрузить страницу.",
    )
    svc = MagicMock(spec=LinkService)
    svc.summarize = AsyncMock(side_effect=ScrapingError("still failing"))

    await cb_link_retry(cb, link_service=svc)

    error_call = cb.message.edit_text.call_args_list[1]
    keyboard = error_call[1].get("reply_markup")
    assert keyboard is not None
    assert "Попробовать снова" in keyboard.inline_keyboard[0][0].text


# ── _extract_url_from_status_message ─────────────────────────────────────────


async def test_extract_url_from_status_message_loading() -> None:
    text = "🔗 https://example.com\n\n⏳ Загружаю саммари..."
    assert _extract_url_from_status_message(text) == "https://example.com"


async def test_extract_url_from_status_message_error() -> None:
    text = "🔗 https://example.com\n\n❌ Не удалось загрузить страницу."
    assert _extract_url_from_status_message(text) == "https://example.com"


async def test_extract_url_from_status_message_no_prefix() -> None:
    text = "https://example.com\n\nSome text"
    assert _extract_url_from_status_message(text) == "https://example.com"


# ── cb_link_save ──────────────────────────────────────────────────────────────


async def test_cb_link_save_appends_confirmation_and_removes_keyboard() -> None:
    cb = make_callback("link:save:uuid")
    cb.message.html_text = "🔗 Ссылка сохранена:\nhttps://example.com"

    await cb_link_save(cb)

    cb.answer.assert_awaited_once()
    cb.message.edit_text.assert_awaited_once()
    call_args = cb.message.edit_text.call_args
    text = call_args[0][0]
    assert "Сохранено" in text
    assert "https://example.com" in text
    assert call_args[1]["reply_markup"] is None
    assert call_args[1]["parse_mode"] == "HTML"


async def test_cb_link_save_no_message_returns_early() -> None:
    cb = make_callback("link:save:uuid")
    cb.message = None

    await cb_link_save(cb)

    cb.answer.assert_awaited_once()


async def test_cb_link_save_double_click_does_not_duplicate_confirmation() -> None:
    """If Save fires again on a message already marked Сохранено, do not append twice."""
    cb = make_callback("link:save:uuid")
    cb.message.html_text = "🔗 https://example.com\n\n🔖 <i>Сохранено</i>"

    await cb_link_save(cb)

    # Should not call edit_text again (which would append another "Сохранено")
    cb.message.edit_text.assert_not_awaited()
    # Keyboard should be cleaned up even on repeated click
    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


async def test_cb_link_save_swallows_edit_text_error() -> None:
    """A Telegram 'message is not modified' error on double click must not crash."""
    cb = make_callback("link:save:uuid")
    cb.message.html_text = "🔗 https://example.com"
    cb.message.edit_text = AsyncMock(side_effect=Exception("message is not modified"))

    # Should not raise
    await cb_link_save(cb)
    cb.answer.assert_awaited_once()


# ── cb_link_close ─────────────────────────────────────────────────────────────


async def test_cb_link_close_removes_keyboard() -> None:
    cb = make_callback("link:close:uuid")

    await cb_link_close(cb)

    cb.answer.assert_awaited_once()
    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    # Text must not change
    cb.message.edit_text.assert_not_awaited()


async def test_cb_link_close_no_message_returns_early() -> None:
    cb = make_callback("link:close:uuid")
    cb.message = None

    await cb_link_close(cb)

    cb.answer.assert_awaited_once()


async def test_cb_link_close_swallows_edit_error_on_double_click() -> None:
    """A double click where the keyboard is already gone must not raise."""
    cb = make_callback("link:close:uuid")
    cb.message.edit_reply_markup = AsyncMock(side_effect=Exception("message is not modified"))

    # Should not raise
    await cb_link_close(cb)
    cb.answer.assert_awaited_once()


# ── cb_link_remind ────────────────────────────────────────────────────────────


async def test_cb_link_remind_goes_directly_to_time_input() -> None:
    """Clicking Напомнить skips yes/no and immediately asks for time."""
    cb = make_callback("link:remind:some-item-id")
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await cb_link_remind(cb, state=state)

    from bot.handlers.reminders import ReminderStates

    state.set_state.assert_awaited_once_with(ReminderStates.waiting_for_time)
    cb.message.answer.assert_awaited_once()
    assert "Когда напомнить" in cb.message.answer.call_args[0][0]


async def test_cb_link_remind_stores_item_id_in_fsm() -> None:
    cb = make_callback("link:remind:some-item-id")
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await cb_link_remind(cb, state=state)

    data_stored = state.update_data.call_args[0][0]
    assert data_stored["reminder_item_id"] == "some-item-id"
    assert data_stored["reminder_attempts"] == 0


async def test_cb_link_remind_removes_keyboard() -> None:
    cb = make_callback("link:remind:uuid")
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await cb_link_remind(cb, state=state)

    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


async def test_cb_link_remind_answers_callback() -> None:
    cb = make_callback("link:remind:uuid")
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await cb_link_remind(cb, state=state)

    cb.answer.assert_awaited_once()


async def test_cb_link_remind_no_message_returns_early() -> None:
    cb = make_callback("link:remind:uuid")
    cb.message = None
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await cb_link_remind(cb, state=state)

    state.set_state.assert_not_awaited()


async def test_cb_link_remind_swallows_edit_error_on_double_click() -> None:
    """If the keyboard was already removed, edit_reply_markup raises — must not crash."""
    cb = make_callback("link:remind:uuid")
    cb.message.edit_reply_markup = AsyncMock(side_effect=Exception("message is not modified"))
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    # Should not raise
    await cb_link_remind(cb, state=state)
    # FSM must still be entered even when the keyboard strip failed
    state.set_state.assert_awaited_once()
    cb.message.answer.assert_awaited_once()
