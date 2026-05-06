"""Tests for /search command — FSM mode picker, formatting, pagination."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.exceptions import SemanticSearchUnavailableError
from bot.handlers.search import (
    SearchStates,
    _format_plain_results,
    _format_semantic_results,
    _pagination_keyboard,
    _relevance_bar,
    cb_pick_mode,
    cb_search_page,
    cmd_search,
    receive_search_query,
)
from bot.models.item import Item, ItemType
from bot.services.list_service import ListService
from bot.services.semantic_search_service import SearchResult, SemanticSearchService


def make_message(user_id: int = 1, text: str | None = None) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.text = text
    return msg


def make_callback(data: str, user_id: int = 1) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    # The router checks ``isinstance(callback.message, Message)`` so we must
    # use ``spec=Message`` for the mock to pass that check.
    cb.message = MagicMock(spec=Message)
    cb.message.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    return cb


def make_state(initial: dict | None = None) -> MagicMock:
    state = MagicMock(spec=FSMContext)
    storage: dict = dict(initial or {})
    state.get_data = AsyncMock(side_effect=lambda: dict(storage))

    async def _update(data: dict) -> None:
        storage.update(data)

    state.update_data = AsyncMock(side_effect=_update)
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


def make_item(
    content: str = "note content",
    item_type: ItemType = ItemType.note,
    created_at: datetime | None = None,
) -> MagicMock:
    item = MagicMock(spec=Item)
    item.content = content
    item.type = item_type
    item.created_at = created_at or datetime(2026, 1, 2, tzinfo=UTC)
    return item


def make_search_result(
    *,
    score: float,
    result_type: str = "item",
    title: str = "Title",
    preview_text: str = "Preview",
    item_type: str = "note",
    url: str | None = None,
) -> SearchResult:
    return SearchResult(
        id=uuid.uuid4(),
        type=result_type,  # type: ignore[arg-type]
        title=title,
        preview_text=preview_text,
        score=score,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        item_type=item_type,
        url=url,
    )


# ─── _relevance_bar ──────────────────────────────────────────────────────────


def test_relevance_bar_maps_score_to_dots() -> None:
    assert _relevance_bar(0.95) == "●●●●●"
    assert _relevance_bar(0.9) == "●●●●●"
    assert _relevance_bar(0.8) == "●●●●○"
    assert _relevance_bar(0.75) == "●●●●○"
    assert _relevance_bar(0.7) == "●●●○○"
    assert _relevance_bar(0.6) == "●●●○○"
    assert _relevance_bar(0.5) == "●●○○○"
    assert _relevance_bar(0.45) == "●●○○○"
    assert _relevance_bar(0.3) == "●○○○○"
    assert _relevance_bar(0.0) == "●○○○○"


# ─── _pagination_keyboard ────────────────────────────────────────────────────


def test_pagination_keyboard_none_on_first_page_without_next() -> None:
    assert _pagination_keyboard(page=0, has_next=False, lang="ru") is None


def test_pagination_keyboard_shows_only_next_on_first_page() -> None:
    kb = _pagination_keyboard(page=0, has_next=True, lang="ru")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)
    assert not any("Назад" in t for t in texts)


def test_pagination_keyboard_shows_only_prev_on_last_page() -> None:
    kb = _pagination_keyboard(page=2, has_next=False, lang="ru")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Назад" in t for t in texts)
    assert not any("Вперёд" in t for t in texts)


def test_pagination_keyboard_shows_both_on_middle_page() -> None:
    kb = _pagination_keyboard(page=1, has_next=True, lang="ru")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Назад" in t for t in texts)
    assert any("Вперёд" in t for t in texts)


def test_pagination_keyboard_carries_correct_callback_data() -> None:
    kb = _pagination_keyboard(page=1, has_next=True, lang="ru")
    assert kb is not None
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "search_page:0" in cbs
    assert "search_page:2" in cbs


# ─── _format_plain_results ───────────────────────────────────────────────────


def test_format_plain_results_escapes_query_and_content() -> None:
    items = [make_item(content="<script>alert(1)</script>", item_type=ItemType.note)]
    text = _format_plain_results(items, query="<b>q</b>", page=0, lang="ru")

    assert "&lt;script&gt;" in text
    assert "&lt;b&gt;q&lt;/b&gt;" in text
    # The original HTML must not appear raw.
    assert "<script>" not in text


def test_format_plain_results_shows_type_emoji_and_date() -> None:
    items = [make_item(content="buy milk", item_type=ItemType.task)]
    text = _format_plain_results(items, query="milk", page=0, lang="ru")

    assert "✅" in text
    assert "buy milk" in text
    assert "02.01.2026" in text


def test_format_plain_results_truncates_long_content() -> None:
    long_content = "x" * 200
    items = [make_item(content=long_content)]
    text = _format_plain_results(items, query="x", page=0, lang="ru")

    # Max 80 chars per snippet before ellipsis.
    assert "x" * 80 + "…" in text


# ─── _format_semantic_results ────────────────────────────────────────────────


def test_format_semantic_results_shows_relevance_bar_and_type_label() -> None:
    results = [
        make_search_result(score=0.92, result_type="idea", title="Идея", preview_text="текст")
    ]
    text = _format_semantic_results(results, query="ai", page=0, lang="ru")

    assert "●●●●●" in text
    assert "[идея]" in text
    assert "💡" in text
    assert "Идея" in text
    assert "текст" in text


def test_format_semantic_results_item_uses_specific_label_for_known_type() -> None:
    """Non-idea hits show their concrete ItemType label (note/link/task) and matching emoji."""
    results = [
        make_search_result(
            score=0.5,
            result_type="item",
            title="Some note",
            preview_text="note body",
            item_type="note",
        )
    ]
    text = _format_semantic_results(results, query="q", page=0, lang="ru")

    assert "[заметка]" in text
    assert "📝" in text
    assert "●●○○○" in text


def test_format_semantic_results_item_falls_back_to_record_label_for_unknown_type() -> None:
    """An unknown item_type — defensive fallback — uses the generic 'запись' label."""
    results = [
        make_search_result(
            score=0.5,
            result_type="item",
            title="Some thing",
            preview_text="body",
            item_type="not_a_real_type",
        )
    ]
    text = _format_semantic_results(results, query="q", page=0, lang="ru")

    assert "[запись]" in text
    assert "📄" in text


def test_format_semantic_results_link_shows_title_and_url_in_parentheses() -> None:
    """Smart-search link entries render as ``{title} ({url})`` when both are known."""
    results = [
        make_search_result(
            score=0.7,
            result_type="item",
            title="Cool Article",
            preview_text="The article body starts here…",
            item_type="link",
            url="https://example.com/article",
        )
    ]
    text = _format_semantic_results(results, query="q", page=0, lang="ru")

    assert "Cool Article (https://example.com/article)" in text
    assert "[ссылка]" in text
    assert "🔗" in text
    # The preview line is shown because scraped_text differs from the title.
    assert "The article body starts here" in text


def test_format_semantic_results_link_without_title_shows_only_url() -> None:
    """Smart-search link without a stored title falls back to the bare URL headline."""
    results = [
        make_search_result(
            score=0.5,
            result_type="item",
            title="https://example.com/raw",
            preview_text="",
            item_type="link",
            url="https://example.com/raw",
        )
    ]
    text = _format_semantic_results(results, query="q", page=0, lang="ru")

    # No "()" around a duplicated URL — the renderer skips the parenthetical
    # when the title equals the URL.
    assert "https://example.com/raw (https://example.com/raw)" not in text
    assert "https://example.com/raw" in text
    # No "Текст:" line because the link has no scraped_text preview.
    assert "Текст:" not in text


def test_format_semantic_results_link_with_no_scraped_text_omits_preview_line() -> None:
    """Issue #124: when scraped_text is empty, the 'Текст:' line is hidden."""
    results = [
        make_search_result(
            score=0.5,
            result_type="item",
            title="My Article",
            preview_text="",
            item_type="link",
            url="https://example.com/page",
        )
    ]
    text = _format_semantic_results(results, query="q", page=0, lang="ru")

    assert "My Article (https://example.com/page)" in text
    assert "Текст:" not in text


def test_format_semantic_results_media_shows_description_and_drive_link() -> None:
    """Smart-search media entries render the Vision description with the Drive link."""
    drive_link = "https://drive.google.com/file/d/abc123"
    results = [
        make_search_result(
            score=0.6,
            result_type="item",
            title="Receipt from supermarket",
            preview_text="Receipt from supermarket",
            item_type="media",
            url=drive_link,
        )
    ]
    text = _format_semantic_results(results, query="q", page=0, lang="ru")

    assert f"Receipt from supermarket ({drive_link})" in text
    assert "[медиа]" in text


def test_format_semantic_results_skips_preview_when_equal_to_title() -> None:
    results = [make_search_result(score=0.5, result_type="item", title="same", preview_text="same")]
    text = _format_semantic_results(results, query="q", page=0, lang="ru")

    # Expect exactly one "same" — duplicated preview should be omitted.
    assert text.count("same") == 1


def test_format_semantic_results_escapes_html_in_title_and_preview() -> None:
    results = [
        make_search_result(
            score=0.5,
            result_type="item",
            title="<b>title</b>",
            preview_text="<i>preview</i>",
        )
    ]
    text = _format_semantic_results(results, query="<q>", page=0, lang="ru")

    assert "&lt;b&gt;" in text
    assert "&lt;i&gt;" in text
    assert "&lt;q&gt;" in text


def test_format_semantic_results_shows_page_number() -> None:
    results = [make_search_result(score=0.5, title="t", preview_text="p")]
    text = _format_semantic_results(results, query="q", page=2, lang="ru")

    assert "стр. 3" in text


# ─── cmd_search — enters FSM ─────────────────────────────────────────────────


async def test_cmd_search_enters_choosing_mode() -> None:
    msg = make_message()
    state = make_state()

    await cmd_search(msg, state=state, lang="ru")

    state.clear.assert_awaited_once()
    state.set_state.assert_awaited_once_with(SearchStates.choosing_mode)
    msg.answer.assert_awaited_once()
    _, kwargs = msg.answer.call_args
    kb = kwargs.get("reply_markup")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Обычный" in t for t in texts)
    assert any("Умный" in t for t in texts)


# ─── cb_pick_mode ────────────────────────────────────────────────────────────


async def test_cb_pick_mode_plain_advances_to_query_prompt() -> None:
    cb = make_callback("search_mode:plain")
    state = make_state()

    await cb_pick_mode(cb, state=state, lang="ru")

    state.update_data.assert_awaited_once_with({"search_mode": "plain"})
    state.set_state.assert_awaited_once_with(SearchStates.waiting_query)
    cb.message.edit_text.assert_awaited_once()
    assert "Введите запрос" in cb.message.edit_text.call_args[0][0]


async def test_cb_pick_mode_smart_uses_smart_prompt() -> None:
    cb = make_callback("search_mode:smart")
    state = make_state()

    await cb_pick_mode(cb, state=state, lang="ru")

    state.update_data.assert_awaited_once_with({"search_mode": "smart"})
    assert "умного" in cb.message.edit_text.call_args[0][0].lower()


async def test_cb_pick_mode_ignores_unknown_mode() -> None:
    cb = make_callback("search_mode:unknown")
    state = make_state()

    await cb_pick_mode(cb, state=state, lang="ru")

    state.update_data.assert_not_awaited()
    state.set_state.assert_not_awaited()
    cb.message.edit_text.assert_not_awaited()


async def test_cb_pick_mode_falls_back_to_answer_on_edit_failure() -> None:
    cb = make_callback("search_mode:plain")
    cb.message.edit_text = AsyncMock(side_effect=Exception("not modified"))
    state = make_state()

    await cb_pick_mode(cb, state=state, lang="ru")

    cb.message.answer.assert_awaited_once()


# ─── receive_search_query — plain path ───────────────────────────────────────


async def test_receive_search_query_plain_shows_results() -> None:
    msg = make_message(text="milk")
    state = make_state({"search_mode": "plain"})
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[make_item("buy milk", ItemType.task)])

    await receive_search_query(
        msg, state=state, list_service=svc, semantic_search_service=None, lang="ru"
    )

    svc.search.assert_awaited_once_with(1, "milk")
    state.set_state.assert_awaited_with(SearchStates.showing_results)
    state.update_data.assert_any_await({"search_query": "milk"})
    reply = msg.answer.call_args[0][0]
    assert "buy milk" in reply
    assert "✅" in reply


async def test_receive_search_query_plain_no_results_stays_in_query_state() -> None:
    msg = make_message(text="unicorn")
    state = make_state({"search_mode": "plain"})
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[])

    await receive_search_query(
        msg, state=state, list_service=svc, semantic_search_service=None, lang="ru"
    )

    # Stays in waiting_query — no transition to showing_results.
    for call in state.set_state.await_args_list:
        assert call.args[0] != SearchStates.showing_results
    text = msg.answer.call_args[0][0]
    assert "ничего не найдено" in text.lower()


async def test_receive_search_query_empty_query_asks_for_text() -> None:
    msg = make_message(text="   ")
    state = make_state({"search_mode": "plain"})
    svc = MagicMock(spec=ListService)

    await receive_search_query(
        msg, state=state, list_service=svc, semantic_search_service=None, lang="ru"
    )

    svc.search = AsyncMock()  # ensure no search ran
    assert "пустой" in msg.answer.call_args[0][0].lower()


async def test_receive_search_query_plain_no_service_sends_error() -> None:
    msg = make_message(text="milk")
    state = make_state({"search_mode": "plain"})

    await receive_search_query(
        msg, state=state, list_service=None, semantic_search_service=None, lang="ru"
    )

    assert "временно недоступен" in msg.answer.call_args[0][0].lower()


async def test_receive_search_query_plain_paginates_when_many_results() -> None:
    msg = make_message(text="item")
    state = make_state({"search_mode": "plain"})
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[make_item(f"item {i}") for i in range(10)])

    await receive_search_query(
        msg, state=state, list_service=svc, semantic_search_service=None, lang="ru"
    )

    _, kwargs = msg.answer.call_args
    kb = kwargs.get("reply_markup")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)


# ─── receive_search_query — smart path ───────────────────────────────────────


async def test_receive_search_query_smart_shows_results() -> None:
    msg = make_message(text="rockets")
    state = make_state({"search_mode": "smart"})
    svc = MagicMock(spec=SemanticSearchService)
    svc.search = AsyncMock(
        return_value=[make_search_result(score=0.8, title="Build a rocket", preview_text="body")]
    )

    await receive_search_query(
        msg, state=state, list_service=None, semantic_search_service=svc, lang="ru"
    )

    svc.search.assert_awaited_once_with(1, "rockets", limit=5, offset=0)
    state.update_data.assert_any_await({"search_query": "rockets"})
    reply = msg.answer.call_args[0][0]
    assert "Build a rocket" in reply
    assert "●●●●○" in reply


async def test_receive_search_query_smart_no_service_sends_error() -> None:
    msg = make_message(text="rockets")
    state = make_state({"search_mode": "smart"})

    await receive_search_query(
        msg, state=state, list_service=None, semantic_search_service=None, lang="ru"
    )

    text = msg.answer.call_args[0][0]
    assert "обычный поиск" in text.lower()


async def test_receive_search_query_smart_unavailable_sends_fallback_message() -> None:
    msg = make_message(text="rockets")
    state = make_state({"search_mode": "smart"})
    svc = MagicMock(spec=SemanticSearchService)
    svc.search = AsyncMock(side_effect=SemanticSearchUnavailableError())

    await receive_search_query(
        msg, state=state, list_service=None, semantic_search_service=svc, lang="ru"
    )

    assert "обычный поиск" in msg.answer.call_args[0][0].lower()


async def test_receive_search_query_smart_no_hits_shows_try_rephrasing() -> None:
    msg = make_message(text="rockets")
    state = make_state({"search_mode": "smart"})
    svc = MagicMock(spec=SemanticSearchService)
    svc.search = AsyncMock(return_value=[])

    await receive_search_query(
        msg, state=state, list_service=None, semantic_search_service=svc, lang="ru"
    )

    assert "перефраз" in msg.answer.call_args[0][0].lower()


async def test_receive_search_query_smart_paginates_on_full_page() -> None:
    msg = make_message(text="ai")
    state = make_state({"search_mode": "smart"})
    svc = MagicMock(spec=SemanticSearchService)
    svc.search = AsyncMock(
        return_value=[make_search_result(score=0.5, title=f"r{i}") for i in range(5)]
    )

    await receive_search_query(
        msg, state=state, list_service=None, semantic_search_service=svc, lang="ru"
    )

    _, kwargs = msg.answer.call_args
    kb = kwargs.get("reply_markup")
    assert kb is not None
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Вперёд" in t for t in texts)


# ─── cb_search_page ──────────────────────────────────────────────────────────


async def test_cb_search_page_edits_message_with_next_page_plain() -> None:
    cb = make_callback("search_page:1")
    state = make_state({"search_mode": "plain", "search_query": "item"})
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[make_item(f"item {i}") for i in range(10)])

    await cb_search_page(cb, state=state, list_service=svc, semantic_search_service=None, lang="ru")

    cb.message.edit_text.assert_awaited_once()
    assert "стр. 2" in cb.message.edit_text.call_args[0][0]


async def test_cb_search_page_uses_semantic_for_smart_mode() -> None:
    cb = make_callback("search_page:1")
    state = make_state({"search_mode": "smart", "search_query": "ai"})
    svc = MagicMock(spec=SemanticSearchService)
    svc.search = AsyncMock(return_value=[make_search_result(score=0.5)])

    await cb_search_page(cb, state=state, list_service=None, semantic_search_service=svc, lang="ru")

    svc.search.assert_awaited_once_with(1, "ai", limit=5, offset=5)
    cb.message.edit_text.assert_awaited_once()


async def test_cb_search_page_invalid_page_is_ignored() -> None:
    cb = make_callback("search_page:notanint")
    state = make_state({"search_mode": "plain", "search_query": "x"})
    svc = MagicMock(spec=ListService)

    await cb_search_page(cb, state=state, list_service=svc, semantic_search_service=None, lang="ru")

    cb.message.edit_text.assert_not_awaited()


async def test_cb_search_page_negative_page_is_ignored() -> None:
    cb = make_callback("search_page:-1")
    state = make_state({"search_mode": "plain", "search_query": "x"})
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[make_item("x")])

    await cb_search_page(cb, state=state, list_service=svc, semantic_search_service=None, lang="ru")

    cb.message.edit_text.assert_not_awaited()


async def test_cb_search_page_without_stored_query_is_ignored() -> None:
    cb = make_callback("search_page:1")
    state = make_state({"search_mode": "plain"})  # no search_query
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock()

    await cb_search_page(cb, state=state, list_service=svc, semantic_search_service=None, lang="ru")

    svc.search.assert_not_awaited()
    cb.message.edit_text.assert_not_awaited()


async def test_cb_search_page_edit_failure_is_silenced() -> None:
    cb = make_callback("search_page:0")
    cb.message.edit_text = AsyncMock(side_effect=Exception("not modified"))
    state = make_state({"search_mode": "plain", "search_query": "x"})
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[make_item("x")])

    # Should not raise.
    await cb_search_page(cb, state=state, list_service=svc, semantic_search_service=None, lang="ru")


async def test_cb_search_page_plain_out_of_range_bounces_to_first_page() -> None:
    """Paging past the end for plain search wraps back to page 0 instead of going blank."""
    cb = make_callback("search_page:5")
    state = make_state({"search_mode": "plain", "search_query": "item"})
    svc = MagicMock(spec=ListService)
    svc.search = AsyncMock(return_value=[make_item(f"item {i}") for i in range(3)])

    await cb_search_page(cb, state=state, list_service=svc, semantic_search_service=None, lang="ru")

    cb.message.edit_text.assert_awaited_once()
    # Shows page 1 (page=0 in zero-indexed state), not "стр. 6".
    assert "стр. 1" in cb.message.edit_text.call_args[0][0]


async def test_cb_search_page_semantic_unavailable_shows_error_inline() -> None:
    cb = make_callback("search_page:1")
    state = make_state({"search_mode": "smart", "search_query": "ai"})
    svc = MagicMock(spec=SemanticSearchService)
    svc.search = AsyncMock(side_effect=SemanticSearchUnavailableError())

    await cb_search_page(cb, state=state, list_service=None, semantic_search_service=svc, lang="ru")

    cb.message.edit_text.assert_awaited_once()
    text, kwargs = cb.message.edit_text.call_args[0][0], cb.message.edit_text.call_args[1]
    assert "обычный поиск" in text.lower()
    # Error replaces the previous pagination controls.
    assert kwargs.get("reply_markup") is None
