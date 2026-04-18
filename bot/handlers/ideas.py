import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.i18n import t
from bot.models.idea import IdeaComplexity, IdeaEffort
from bot.services.idea_service import IdeaService, IdeasPage

_COMPLEXITY_KEY = {
    IdeaComplexity.simple: "idea_complexity_simple",
    IdeaComplexity.medium: "idea_complexity_medium",
    IdeaComplexity.complex: "idea_complexity_complex",
}

_EFFORT_KEY = {
    IdeaEffort.quick: "idea_effort_quick",
    IdeaEffort.halfday: "idea_effort_halfday",
    IdeaEffort.day: "idea_effort_day",
    IdeaEffort.longterm: "idea_effort_longterm",
}


# Legacy RU-only labels kept for backwards-compatible imports (tests + voice handler
# fall back to them when no language is in scope). Prefer ``complexity_label()``
# and ``effort_label()`` in new code.
_COMPLEXITY_LABEL = {
    IdeaComplexity.simple: "простая",
    IdeaComplexity.medium: "средняя",
    IdeaComplexity.complex: "сложная",
}

_EFFORT_LABEL = {
    IdeaEffort.quick: "< 1ч",
    IdeaEffort.halfday: "1–4ч",
    IdeaEffort.day: "4–8ч",
    IdeaEffort.longterm: "долгосрочно",
}


def complexity_label(complexity: IdeaComplexity, lang: str) -> str:
    """Return the localized complexity label for an idea."""
    return t(_COMPLEXITY_KEY[complexity], lang)


def effort_label(effort: IdeaEffort, lang: str) -> str:
    """Return the localized effort label for an idea."""
    return t(_EFFORT_KEY[effort], lang)


logger = logging.getLogger(__name__)

router = Router(name="ideas")


def _format_ideas_page(ideas_page: IdeasPage, lang: str) -> str:
    """Format a page of ideas as a text message."""
    lines = [t("ideas_header", lang, page=ideas_page.page + 1)]
    start_num = ideas_page.page * 10 + 1
    for i, (item, idea) in enumerate(ideas_page.rows, start_num):
        snippet = item.content[:80] + ("…" if len(item.content) > 80 else "")
        tags_str = " ".join(f"#{tag}" for tag in idea.tags) if idea.tags else ""
        date_str = item.created_at.strftime("%d.%m.%Y")
        entry = f"{i}. {snippet}"
        meta_parts = []
        if idea.complexity:
            meta_parts.append(complexity_label(idea.complexity, lang))
        if idea.effort:
            meta_parts.append(effort_label(idea.effort, lang))
        if meta_parts:
            entry += f" <i>({', '.join(meta_parts)})</i>"
        if tags_str:
            entry += f"\n   {tags_str}"
        entry += f"  <i>{date_str}</i>"
        lines.append(entry)

    lines.append(t("ideas_total", lang, total=ideas_page.total))
    return "\n\n".join(lines)


def _ideas_keyboard(ideas_page: IdeasPage, lang: str) -> InlineKeyboardMarkup | None:
    """Build prev/next pagination keyboard; return None if only one page."""
    if not ideas_page.has_prev and not ideas_page.has_next:
        return None
    buttons = []
    if ideas_page.has_prev:
        buttons.append(
            InlineKeyboardButton(
                text=t("pagination_prev", lang),
                callback_data=f"ideas_page:{ideas_page.page - 1}",
            )
        )
    if ideas_page.has_next:
        buttons.append(
            InlineKeyboardButton(
                text=t("pagination_next", lang),
                callback_data=f"ideas_page:{ideas_page.page + 1}",
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


@router.message(Command("ideas"))
async def handle_ideas_command(
    message: Message,
    idea_service: IdeaService | None = None,
    lang: str = "en",
) -> None:
    """Show the user's saved ideas list with pagination."""
    if idea_service is None:
        logger.warning("idea_service not injected — DI misconfiguration")
        await message.answer(t("ideas_command_unavailable", lang))
        return

    user_id = message.from_user.id if message.from_user else 0
    ideas_page = await idea_service.get_page(user_id, page=0)

    if ideas_page.total == 0:
        await message.answer(t("ideas_empty", lang))
        return

    reply = _format_ideas_page(ideas_page, lang)
    kb = _ideas_keyboard(ideas_page, lang)
    await message.answer(reply, reply_markup=kb)


@router.callback_query(F.data.startswith("ideas_page:"))
async def cb_ideas_page(
    callback: CallbackQuery,
    idea_service: IdeaService | None = None,
    lang: str = "en",
) -> None:
    """Handle pagination for /ideas."""
    await callback.answer()
    if idea_service is None or callback.message is None:
        return

    try:
        page = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    except (ValueError, IndexError):
        logger.warning("Invalid ideas_page callback data: %s", callback.data)
        return

    user_id = callback.from_user.id
    ideas_page = await idea_service.get_page(user_id, page=page)
    reply = _format_ideas_page(ideas_page, lang)
    kb = _ideas_keyboard(ideas_page, lang)
    try:
        await callback.message.edit_text(reply, reply_markup=kb)
    except Exception:
        logger.warning("Could not edit ideas message (already deleted or unchanged)")
