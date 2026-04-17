"""/search command: FSM that lets the user pick a search mode and run the query.

Step 1 — user chooses between plain full-text search and smart (semantic) search.
Step 2 — bot asks for the query.
Step 3 — user sends the query; bot runs the chosen search and paginates the results.

The current search mode and query are kept in FSM state so pagination callbacks
can re-run the same search for a different page without re-asking the user.
"""

import html
import logging
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.exceptions import SemanticSearchUnavailableError
from bot.models.item import Item, ItemType
from bot.services.list_service import ListService
from bot.services.semantic_search_service import SearchResult, SemanticSearchService

logger = logging.getLogger(__name__)

router = Router(name="search")


class SearchStates(StatesGroup):
    """FSM states for the /search dialog."""

    choosing_mode = State()
    waiting_query = State()
    showing_results = State()


# FSM state keys.
_MODE_KEY = "search_mode"  # "plain" | "smart"
_QUERY_KEY = "search_query"

# Callback data prefixes — kept short to stay within Telegram's 64-byte limit.
_CB_MODE = "search_mode:"
_CB_PAGE = "search_page:"

# Search result modes.
_MODE_PLAIN = "plain"
_MODE_SMART = "smart"

_PAGE_SIZE = 5

# User-facing messages reused across happy/failure paths.
_SERVICE_UNAVAILABLE_MSG = "Поиск временно недоступен. Попробуйте позже."
_SEMANTIC_UNAVAILABLE_MSG = "Умный поиск временно недоступен. Попробуйте обычный поиск."
_NO_RESULTS_MSG = "Ничего не найдено. Попробуйте перефразировать запрос."

# Emoji per Item type, mirrored from bot/handlers/commands.py so the two
# listings look the same.
_TYPE_EMOJI = {
    ItemType.link: "🔗",
    ItemType.note: "📝",
    ItemType.task: "✅",
    ItemType.media: "🖼️",
    ItemType.idea: "💡",
}

# Human-readable labels for semantic results. Items of type ``media`` do not
# participate in semantic search but are kept here for completeness.
_TYPE_LABEL = {
    ItemType.link: "ссылка",
    ItemType.note: "заметка",
    ItemType.task: "задача",
    ItemType.media: "медиа",
    ItemType.idea: "идея",
}

_PREVIEW_CHARS = 100


@dataclass(frozen=True)
class _SearchOutcome:
    """Structured result of a search run — either a page to render or an error."""

    # When ``reply`` is ``None`` the caller must render ``error_message`` instead.
    reply: str | None
    keyboard: InlineKeyboardMarkup | None
    error_message: str | None


def _mode_keyboard() -> InlineKeyboardMarkup:
    """Build the step-1 keyboard offering the two search modes."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔍 Обычный", callback_data=f"{_CB_MODE}{_MODE_PLAIN}"),
                InlineKeyboardButton(
                    text="🧠 Умный (AI)", callback_data=f"{_CB_MODE}{_MODE_SMART}"
                ),
            ]
        ]
    )


def _relevance_bar(score: float) -> str:
    """Return a five-dot relevance indicator for a cosine-similarity ``score``."""
    if score >= 0.9:
        return "●●●●●"
    if score >= 0.75:
        return "●●●●○"
    if score >= 0.6:
        return "●●●○○"
    if score >= 0.45:
        return "●●○○○"
    return "●○○○○"


def _truncate(text: str, limit: int = _PREVIEW_CHARS) -> str:
    """Cut ``text`` to ``limit`` characters, appending an ellipsis on overflow."""
    stripped = (text or "").strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "…"


def _has_prev(page: int) -> bool:
    """True when there is at least one earlier page."""
    return page > 0


def _pagination_keyboard(page: int, has_next: bool) -> InlineKeyboardMarkup | None:
    """Build prev/next pagination keyboard; return ``None`` when both disabled."""
    buttons: list[InlineKeyboardButton] = []
    if _has_prev(page):
        buttons.append(InlineKeyboardButton(text="← Назад", callback_data=f"{_CB_PAGE}{page - 1}"))
    if has_next:
        buttons.append(InlineKeyboardButton(text="Вперёд →", callback_data=f"{_CB_PAGE}{page + 1}"))
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _format_plain_results(items: list[Item], query: str, page: int) -> str:
    """Format a page of plain full-text search results."""
    safe_query = html.escape(query)
    lines = [f"🔍 <b>Результаты по «{safe_query}»</b> (стр. {page + 1}):\n"]
    for item in items:
        emoji = _TYPE_EMOJI.get(item.type, "📄")
        snippet = html.escape(_truncate(item.content, 80))
        date_str = item.created_at.strftime("%d.%m.%Y")
        lines.append(f"{emoji} {snippet}  <i>{date_str}</i>")
    return "\n".join(lines)


def _format_semantic_results(results: list[SearchResult], query: str, page: int) -> str:
    """Format a page of semantic search results with relevance bars."""
    safe_query = html.escape(query)
    lines = [f"🧠 <b>Умный поиск по «{safe_query}»</b> (стр. {page + 1}):\n"]
    for result in results:
        label, emoji = _semantic_header_parts(result)
        title = html.escape(_truncate(result.title, _PREVIEW_CHARS))
        preview = html.escape(_truncate(result.preview_text, _PREVIEW_CHARS))
        bar = _relevance_bar(result.score)
        entry = f"{emoji} <b>[{label}]</b> {title}\nРелевантность: {bar}"
        if preview and preview != title:
            entry += f"\nТекст: {preview}"
        lines.append(entry)
    return "\n\n".join(lines)


def _semantic_header_parts(result: SearchResult) -> tuple[str, str]:
    """Map a ``SearchResult`` to the (label, emoji) used in its header."""
    if result.type == "idea":
        return _TYPE_LABEL[ItemType.idea], _TYPE_EMOJI[ItemType.idea]
    # ``SearchResult`` does not carry the ItemType for non-idea items, so we
    # fall back to a generic record label. In practice the emoji/label distinguish
    # ideas from other items, which is the most important visual cue.
    return "запись", "📄"


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext) -> None:
    """Enter the /search FSM by asking the user to pick a search mode."""
    await state.clear()
    await state.set_state(SearchStates.choosing_mode)
    await message.answer(
        "Какой поиск запустить?\n\n"
        "<b>🔍 Обычный</b> — ищет по точному вхождению текста.\n"
        "<b>🧠 Умный (AI)</b> — понимает смысл запроса, а не только слова.",
        reply_markup=_mode_keyboard(),
    )


@router.callback_query(SearchStates.choosing_mode, F.data.startswith(_CB_MODE))
async def cb_pick_mode(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle mode selection — remember the choice and ask for the query."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    if not isinstance(callback.message, Message):
        return

    mode = callback.data.removeprefix(_CB_MODE)
    if mode not in (_MODE_PLAIN, _MODE_SMART):
        return

    await state.update_data({_MODE_KEY: mode})
    await state.set_state(SearchStates.waiting_query)
    prompt = "Введите запрос для умного поиска:" if mode == _MODE_SMART else "Введите запрос:"
    try:
        await callback.message.edit_text(prompt, reply_markup=None)
    except Exception:
        # If the mode-picker message can't be edited (e.g. already modified)
        # we still move forward by sending the prompt as a new message.
        await callback.message.answer(prompt)


@router.message(SearchStates.waiting_query)
async def receive_search_query(
    message: Message,
    state: FSMContext,
    list_service: ListService | None = None,
    semantic_search_service: SemanticSearchService | None = None,
) -> None:
    """Run the chosen search against ``message.text`` and reply with results."""
    query = (message.text or "").strip()
    if not query:
        await message.answer("Пустой запрос. Введите текст или /cancel.")
        return

    data = await state.get_data()
    mode = data.get(_MODE_KEY, _MODE_PLAIN)

    user_id = message.from_user.id if message.from_user else 0
    outcome = await _run_search(
        mode=mode,
        query=query,
        user_id=user_id,
        page=0,
        list_service=list_service,
        semantic_search_service=semantic_search_service,
    )

    if outcome.reply is None:
        # Error path: user stays in ``waiting_query`` so they can try again or /cancel.
        assert outcome.error_message is not None
        await message.answer(outcome.error_message)
        return

    await state.update_data({_QUERY_KEY: query})
    await state.set_state(SearchStates.showing_results)
    await message.answer(outcome.reply, reply_markup=outcome.keyboard)


@router.callback_query(SearchStates.showing_results, F.data.startswith(_CB_PAGE))
async def cb_search_page(
    callback: CallbackQuery,
    state: FSMContext,
    list_service: ListService | None = None,
    semantic_search_service: SemanticSearchService | None = None,
) -> None:
    """Handle pagination for the current search — re-run the stored query."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    if not isinstance(callback.message, Message):
        return

    try:
        page = int(callback.data.removeprefix(_CB_PAGE))
    except ValueError:
        logger.warning("Invalid search_page callback data: %s", callback.data)
        return
    if page < 0:
        return

    data = await state.get_data()
    mode = data.get(_MODE_KEY, _MODE_PLAIN)
    query = data.get(_QUERY_KEY, "")
    if not query:
        return

    user_id = callback.from_user.id
    outcome = await _run_search(
        mode=mode,
        query=query,
        user_id=user_id,
        page=page,
        list_service=list_service,
        semantic_search_service=semantic_search_service,
    )

    text = outcome.reply if outcome.reply is not None else outcome.error_message
    keyboard = outcome.keyboard if outcome.reply is not None else None
    if text is None:
        return

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        logger.warning("Could not edit search results message (already deleted or unchanged)")


async def _run_search(
    *,
    mode: str,
    query: str,
    user_id: int,
    page: int,
    list_service: ListService | None,
    semantic_search_service: SemanticSearchService | None,
) -> _SearchOutcome:
    """Run the search for ``mode`` and return a structured outcome."""
    if mode == _MODE_SMART:
        return await _run_semantic_search(
            query=query, user_id=user_id, page=page, service=semantic_search_service
        )
    return await _run_plain_search(query=query, user_id=user_id, page=page, service=list_service)


async def _run_plain_search(
    *,
    query: str,
    user_id: int,
    page: int,
    service: ListService | None,
) -> _SearchOutcome:
    """Run the plain full-text search and build the reply for ``page``."""
    if service is None:
        logger.warning("list_service not injected — DI misconfiguration")
        return _SearchOutcome(reply=None, keyboard=None, error_message=_SERVICE_UNAVAILABLE_MSG)

    # ``ListService.search`` currently returns a flat capped list, so we page
    # client-side. This keeps behaviour consistent with the pre-FSM search.
    all_items = await service.search(user_id, query)
    if not all_items:
        return _SearchOutcome(reply=None, keyboard=None, error_message=_NO_RESULTS_MSG)

    start = page * _PAGE_SIZE
    page_items = all_items[start : start + _PAGE_SIZE]
    if not page_items:
        # Page is out of range — bounce the user to the first page rather than
        # rendering an empty list.
        page = 0
        page_items = all_items[:_PAGE_SIZE]

    has_next = len(all_items) > (page + 1) * _PAGE_SIZE
    text = _format_plain_results(page_items, query, page)
    keyboard = _pagination_keyboard(page, has_next)
    return _SearchOutcome(reply=text, keyboard=keyboard, error_message=None)


async def _run_semantic_search(
    *,
    query: str,
    user_id: int,
    page: int,
    service: SemanticSearchService | None,
) -> _SearchOutcome:
    """Run the AI semantic search and build the reply for ``page``."""
    if service is None:
        logger.warning("semantic_search_service not injected — DI misconfiguration")
        return _SearchOutcome(reply=None, keyboard=None, error_message=_SEMANTIC_UNAVAILABLE_MSG)

    try:
        results = await service.search(user_id, query, limit=_PAGE_SIZE, offset=page * _PAGE_SIZE)
    except SemanticSearchUnavailableError:
        return _SearchOutcome(reply=None, keyboard=None, error_message=_SEMANTIC_UNAVAILABLE_MSG)

    if not results:
        return _SearchOutcome(reply=None, keyboard=None, error_message=_NO_RESULTS_MSG)

    # The service returns up to ``limit`` rows; a full page implies there may
    # be a next page available. Semantic scores are monotonic per page, so
    # this is the best hint we have without an extra count query.
    has_next = len(results) >= _PAGE_SIZE
    text = _format_semantic_results(results, query, page)
    keyboard = _pagination_keyboard(page, has_next)
    return _SearchOutcome(reply=text, keyboard=keyboard, error_message=None)
