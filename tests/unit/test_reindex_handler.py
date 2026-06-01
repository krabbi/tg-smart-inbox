"""Tests for the single-record reindex callback handler and its keyboard helpers."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.handlers.reindex import (
    _parse_callback,
    handle_reindex_one,
    idea_retry_keyboard,
    item_retry_keyboard,
    retry_keyboard,
)
from bot.services.reindex_service import ReindexResult, ReindexService


def make_callback(data: str, *, with_message: bool = True, user_id: int = 1) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    if with_message:
        cb.message = MagicMock(spec=Message)
        cb.message.edit_text = AsyncMock()
        cb.message.answer = AsyncMock()
    else:
        cb.message = None
    return cb


def make_reindex_service(
    *,
    item_result: ReindexResult | None = None,
    idea_result: ReindexResult | None = None,
) -> MagicMock:
    svc = MagicMock(spec=ReindexService)
    svc.reindex_item = AsyncMock(return_value=item_result)
    svc.reindex_idea = AsyncMock(return_value=idea_result)
    return svc


# ── Keyboard helpers ─────────────────────────────────────────────────────────


def test_item_retry_keyboard_emits_item_callback() -> None:
    item_id = uuid.uuid4()
    kb = item_retry_keyboard(item_id, lang="ru")
    assert isinstance(kb, InlineKeyboardMarkup)
    button = kb.inline_keyboard[0][0]
    assert button.callback_data == f"reindex:item:{item_id}"
    assert "Попробовать" in button.text


def test_idea_retry_keyboard_emits_idea_callback() -> None:
    idea_id = uuid.uuid4()
    kb = idea_retry_keyboard(idea_id, lang="en")
    button = kb.inline_keyboard[0][0]
    assert button.callback_data == f"reindex:idea:{idea_id}"
    assert "Try again" in button.text


def test_retry_keyboard_unknown_kind_falls_back_to_item() -> None:
    """Defensive: an unexpected kind string is treated as item to avoid losing the action."""
    record_id = uuid.uuid4()
    kb = retry_keyboard("bogus", record_id, lang="en")
    assert kb.inline_keyboard[0][0].callback_data == f"reindex:item:{record_id}"


def test_callback_data_fits_in_telegram_64_byte_limit() -> None:
    """``reindex:idea:<uuid>`` must stay within Telegram's hard 64-byte cap."""
    kb = idea_retry_keyboard(uuid.uuid4(), lang="ru")
    payload = kb.inline_keyboard[0][0].callback_data
    assert payload is not None
    assert len(payload.encode("utf-8")) <= 64


# ── _parse_callback ──────────────────────────────────────────────────────────


def test_parse_callback_accepts_item_form() -> None:
    record_id = uuid.uuid4()
    parsed = _parse_callback(f"reindex:item:{record_id}")
    assert parsed == ("item", record_id)


def test_parse_callback_accepts_idea_form() -> None:
    record_id = uuid.uuid4()
    parsed = _parse_callback(f"reindex:idea:{record_id}")
    assert parsed == ("idea", record_id)


def test_parse_callback_rejects_unknown_prefix() -> None:
    assert _parse_callback(f"other:item:{uuid.uuid4()}") is None


def test_parse_callback_rejects_unknown_kind() -> None:
    assert _parse_callback(f"reindex:foo:{uuid.uuid4()}") is None


def test_parse_callback_rejects_bad_uuid() -> None:
    assert _parse_callback("reindex:item:not-a-uuid") is None


def test_parse_callback_rejects_truncated_payload() -> None:
    assert _parse_callback("reindex:item") is None


# ── handle_reindex_one ───────────────────────────────────────────────────────


async def test_reindex_success_for_item_edits_message_and_removes_keyboard() -> None:
    record_id = uuid.uuid4()
    cb = make_callback(f"reindex:item:{record_id}")
    svc = make_reindex_service(item_result=ReindexResult.SUCCESS)

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    svc.reindex_item.assert_awaited_once_with(record_id, 1)
    cb.answer.assert_awaited_once_with()
    cb.message.edit_text.assert_awaited_once()
    args, kwargs = cb.message.edit_text.call_args
    assert "проиндексирована" in args[0]
    assert kwargs.get("reply_markup") is None


async def test_reindex_success_for_idea_routes_to_idea_method() -> None:
    record_id = uuid.uuid4()
    cb = make_callback(f"reindex:idea:{record_id}", user_id=77)
    svc = make_reindex_service(idea_result=ReindexResult.SUCCESS)

    await handle_reindex_one(cb, reindex_service=svc, lang="en")

    svc.reindex_idea.assert_awaited_once_with(record_id, 77)
    svc.reindex_item.assert_not_awaited()
    cb.message.edit_text.assert_awaited_once()
    args, kwargs = cb.message.edit_text.call_args
    assert "indexed" in args[0].lower()
    assert kwargs.get("reply_markup") is None


async def test_reindex_service_unavailable_keeps_keyboard() -> None:
    record_id = uuid.uuid4()
    cb = make_callback(f"reindex:item:{record_id}")
    svc = make_reindex_service(item_result=ReindexResult.SERVICE_UNAVAILABLE)

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    cb.answer.assert_awaited_once_with()
    cb.message.edit_text.assert_awaited_once()
    args, kwargs = cb.message.edit_text.call_args
    assert "всё ещё недоступен" in args[0]
    keyboard = kwargs.get("reply_markup")
    assert isinstance(keyboard, InlineKeyboardMarkup)
    # Same button is re-attached so the user can try again.
    assert keyboard.inline_keyboard[0][0].callback_data == f"reindex:item:{record_id}"


async def test_reindex_already_indexed_shows_alert_and_replaces_with_success() -> None:
    record_id = uuid.uuid4()
    cb = make_callback(f"reindex:item:{record_id}")
    svc = make_reindex_service(item_result=ReindexResult.ALREADY_INDEXED)

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    cb.answer.assert_awaited_once()
    alert_args, alert_kwargs = cb.answer.call_args
    assert "проиндексирована" in alert_args[0]
    assert alert_kwargs.get("show_alert") is True
    cb.message.edit_text.assert_awaited_once()
    args, kwargs = cb.message.edit_text.call_args
    assert kwargs.get("reply_markup") is None


async def test_reindex_not_found_shows_alert_and_leaves_message_untouched() -> None:
    """A forged callback ID must never edit the chat history — only flash an alert."""
    record_id = uuid.uuid4()
    cb = make_callback(f"reindex:item:{record_id}")
    svc = make_reindex_service(item_result=ReindexResult.NOT_FOUND)

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    cb.answer.assert_awaited_once()
    alert_args, alert_kwargs = cb.answer.call_args
    assert "не твоя" in alert_args[0]
    assert alert_kwargs.get("show_alert") is True
    cb.message.edit_text.assert_not_awaited()


async def test_reindex_edit_text_failure_falls_back_to_fresh_message() -> None:
    """Telegram refuses edits older than 48h — the user must still see the result."""
    record_id = uuid.uuid4()
    cb = make_callback(f"reindex:item:{record_id}")
    cb.message.edit_text = AsyncMock(side_effect=Exception("message too old"))
    svc = make_reindex_service(item_result=ReindexResult.SUCCESS)

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    cb.message.edit_text.assert_awaited_once()
    cb.message.answer.assert_awaited_once()
    args, _ = cb.message.answer.call_args
    assert "проиндексирована" in args[0]


async def test_reindex_no_service_alerts_user_with_not_configured_message() -> None:
    cb = make_callback(f"reindex:item:{uuid.uuid4()}")

    await handle_reindex_one(cb, reindex_service=None, lang="ru")

    cb.answer.assert_awaited_once()
    args, kwargs = cb.answer.call_args
    assert "не настроен" in args[0]
    assert kwargs.get("show_alert") is True


async def test_reindex_malformed_callback_answers_without_touching_message() -> None:
    cb = make_callback("reindex:item:not-a-uuid")
    svc = make_reindex_service()

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    svc.reindex_item.assert_not_awaited()
    svc.reindex_idea.assert_not_awaited()
    cb.answer.assert_awaited_once()
    cb.message.edit_text.assert_not_awaited()


async def test_reindex_without_message_returns_early() -> None:
    cb = make_callback(f"reindex:item:{uuid.uuid4()}", with_message=False)
    svc = make_reindex_service(item_result=ReindexResult.SUCCESS)

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    svc.reindex_item.assert_not_awaited()
    cb.answer.assert_awaited_once()


async def test_reindex_without_from_user_returns_early() -> None:
    cb = make_callback(f"reindex:item:{uuid.uuid4()}")
    cb.from_user = None
    svc = make_reindex_service(item_result=ReindexResult.SUCCESS)

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    svc.reindex_item.assert_not_awaited()
    cb.answer.assert_awaited_once()


async def test_reindex_service_unavailable_fresh_message_fallback() -> None:
    """When the edit fails for the still-unavailable case, the fallback message keeps the button."""
    record_id = uuid.uuid4()
    cb = make_callback(f"reindex:idea:{record_id}")
    cb.message.edit_text = AsyncMock(side_effect=Exception("too old"))
    svc = make_reindex_service(idea_result=ReindexResult.SERVICE_UNAVAILABLE)

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    cb.message.answer.assert_awaited_once()
    args, kwargs = cb.message.answer.call_args
    assert "всё ещё недоступен" in args[0]
    keyboard = kwargs.get("reply_markup")
    assert isinstance(keyboard, InlineKeyboardMarkup)
    assert keyboard.inline_keyboard[0][0].callback_data == f"reindex:idea:{record_id}"


async def test_reindex_callback_without_data_returns_early() -> None:
    cb = make_callback("reindex:item:irrelevant")
    cb.data = None
    svc = make_reindex_service()

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    svc.reindex_item.assert_not_awaited()
    cb.answer.assert_awaited_once()


async def test_reindex_swallows_answer_failure_so_handler_never_raises() -> None:
    """If both edit_text and the fallback answer raise, the handler still completes silently."""
    record_id = uuid.uuid4()
    cb = make_callback(f"reindex:item:{record_id}")
    cb.message.edit_text = AsyncMock(side_effect=Exception("boom"))
    cb.message.answer = AsyncMock(side_effect=Exception("also boom"))
    svc = make_reindex_service(item_result=ReindexResult.SUCCESS)

    await handle_reindex_one(cb, reindex_service=svc, lang="ru")

    cb.answer.assert_awaited_once()
