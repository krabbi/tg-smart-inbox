import html
import logging
import uuid

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.exceptions import ScrapingError
from bot.handlers.reminders import _ATTEMPTS_KEY, _ITEM_ID_KEY, ReminderStates
from bot.i18n import t
from bot.services.link_service import LinkService

logger = logging.getLogger(__name__)

router = Router(name="links")

_CB_SUMMARY = "link:summary:{item_id}"
_CB_SAVE = "link:save:{item_id}"
_CB_REMIND = "link:remind:{item_id}"
_CB_RETRY = "link:retry:{item_id}"
_CB_CLOSE = "link:close:{item_id}"


def _link_keyboard(item_id: str, lang: str) -> InlineKeyboardMarkup:
    """Build the action keyboard shown after a link is saved."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("link_btn_summary", lang),
                    callback_data=_CB_SUMMARY.format(item_id=item_id),
                ),
                InlineKeyboardButton(
                    text=t("link_btn_save", lang),
                    callback_data=_CB_SAVE.format(item_id=item_id),
                ),
                InlineKeyboardButton(
                    text=t("link_btn_remind", lang),
                    callback_data=_CB_REMIND.format(item_id=item_id),
                ),
            ]
        ]
    )


def _save_keyboard(item_id: str, lang: str) -> InlineKeyboardMarkup:
    """Build keyboard with Save / Remind / Close buttons shown after summary is ready."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("link_btn_save", lang),
                    callback_data=_CB_SAVE.format(item_id=item_id),
                ),
                InlineKeyboardButton(
                    text=t("link_btn_remind", lang),
                    callback_data=_CB_REMIND.format(item_id=item_id),
                ),
                InlineKeyboardButton(
                    text=t("link_btn_close", lang),
                    callback_data=_CB_CLOSE.format(item_id=item_id),
                ),
            ]
        ]
    )


def _retry_keyboard(item_id: str, lang: str) -> InlineKeyboardMarkup:
    """Build keyboard with retry button shown on summarization error."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("link_btn_retry", lang),
                    callback_data=_CB_RETRY.format(item_id=item_id),
                ),
            ]
        ]
    )


def _extract_url(message_text: str) -> str:
    """Extract URL from the saved-link message text."""
    return message_text.split("\n")[-1].strip()


def _parse_item_id(raw: str) -> uuid.UUID | None:
    """Return the callback item_id as a UUID, or ``None`` if it is malformed."""
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError):
        return None


# Shared notice shown across handlers (text, voice, link) when semantic indexing
# is temporarily unavailable at save time. Indexing is retried by the background
# scheduler job. Kept as a constant so existing callers that import it keep working;
# prefer ``t("embedding_unavailable_notice", lang)`` in new code.
EMBEDDING_UNAVAILABLE_NOTICE = "ℹ️ Умный поиск временно недоступен, запись сохранена без индексации."


async def handle_link_message(
    message: Message, url: str, link_service: LinkService, lang: str = "en"
) -> None:
    """Save a link and show action buttons. Called from the messages handler."""
    user_id = message.from_user.id if message.from_user else 0
    saved = await link_service.save(url, user_id)
    keyboard = _link_keyboard(str(saved.item.id), lang)
    await message.answer(t("link_saved", lang, url=url), reply_markup=keyboard)
    if not saved.indexed:
        await message.answer(t("embedding_unavailable_notice", lang))


async def _do_summarize(
    callback: CallbackQuery,
    item_id: str,
    url: str,
    link_service: LinkService,
    lang: str,
    user_id: int,
) -> None:
    """Run the summarize flow: show loading, fetch summary, update message."""
    # Show loading state immediately, preserving URL
    await callback.message.edit_text(  # type: ignore[union-attr]
        t("link_summary_loading", lang, url=url),
        reply_markup=None,
    )

    try:
        parsed_item_id = _parse_item_id(item_id)
        summary = await link_service.summarize(
            url, user_id=user_id, item_id=parsed_item_id, lang=lang
        )
        text = t(
            "link_summary_result",
            lang,
            url=html.escape(url),
            title=html.escape(summary.title),
            body=html.escape(summary.body),
        )
        keyboard = _save_keyboard(item_id, lang)
        await callback.message.edit_text(  # type: ignore[union-attr]
            text, parse_mode="HTML", reply_markup=keyboard
        )
    except ScrapingError as exc:
        logger.warning("Scraping failed for item %s: %s", item_id, exc)
        keyboard = _retry_keyboard(item_id, lang)
        await callback.message.edit_text(  # type: ignore[union-attr]
            t("link_scraping_failed", lang, url=url),
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Unexpected error summarising item %s", item_id)
        keyboard = _retry_keyboard(item_id, lang)
        await callback.message.edit_text(  # type: ignore[union-attr]
            t("link_summary_failed", lang, url=url),
            reply_markup=keyboard,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("link:summary:"))
async def cb_link_summary(
    callback: CallbackQuery, link_service: LinkService, lang: str = "en"
) -> None:
    """Handle [Саммари] button — fetch page and show Claude summary."""
    item_id = callback.data.split(":", 2)[2]  # type: ignore[union-attr]
    url = _extract_url(callback.message.text) if callback.message else ""  # type: ignore[union-attr]
    user_id = callback.from_user.id if callback.from_user else 0

    await callback.answer()
    await _do_summarize(callback, item_id, url, link_service, lang, user_id)


@router.callback_query(lambda c: c.data and c.data.startswith("link:retry:"))
async def cb_link_retry(
    callback: CallbackQuery, link_service: LinkService, lang: str = "en"
) -> None:
    """Handle [Попробовать снова] button — retry summarization."""
    item_id = callback.data.split(":", 2)[2]  # type: ignore[union-attr]
    # URL is on the first line after the emoji prefix
    url = _extract_url_from_status_message(callback.message.text) if callback.message else ""  # type: ignore[union-attr]
    user_id = callback.from_user.id if callback.from_user else 0

    await callback.answer()
    await _do_summarize(callback, item_id, url, link_service, lang, user_id)


def _extract_url_from_status_message(text: str) -> str:
    """Extract URL from a status message (loading/error) where first line is '🔗 <url>'."""
    first_line = text.split("\n")[0].strip()
    # Remove the link emoji prefix
    if first_line.startswith("🔗 "):
        return first_line[len("🔗 ") :]
    return first_line


@router.callback_query(lambda c: c.data and c.data.startswith("link:save:"))
async def cb_link_save(callback: CallbackQuery, lang: str = "en") -> None:
    """Handle [Сохранить] button — confirm save with persistent text."""
    await callback.answer()
    if callback.message is None:
        return
    existing_text = callback.message.html_text or callback.message.text or ""
    confirmation = t("link_saved_confirmation", lang)
    # Guard against double delivery: if the confirmation is already appended,
    # just strip the keyboard instead of appending it again. We check for the
    # localized forms plus a legacy marker to stay idempotent across language
    # switches mid-conversation.
    if (
        confirmation in existing_text
        or "🔖 <i>Сохранено</i>" in existing_text
        or "🔖 <i>Saved</i>" in existing_text
        or "🔖 Сохранено" in existing_text
        or "🔖 Saved" in existing_text
    ):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("edit_reply_markup failed on repeated link:save")
        return
    try:
        await callback.message.edit_text(
            existing_text + f"\n\n{confirmation}",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        logger.debug("edit_text failed on link:save (likely already confirmed)")


@router.callback_query(lambda c: c.data and c.data.startswith("link:close:"))
async def cb_link_close(callback: CallbackQuery) -> None:
    """Handle [Закрыть] button — remove the keyboard without changing the message text."""
    await callback.answer()
    if callback.message is None:
        return
    # edit_reply_markup is idempotent: calling it again with the same (empty) markup
    # is either a no-op or returns a harmless "message is not modified" error, which
    # aiogram surfaces as an exception. Swallow it so a double click never crashes.
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("edit_reply_markup failed on link:close (likely already removed)")


@router.callback_query(lambda c: c.data and c.data.startswith("link:remind:"))
async def cb_link_remind(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    """Handle [⏰ Напомнить] button — go directly to time input, skip yes/no confirmation."""
    await callback.answer()
    if callback.message is None:
        return

    item_id = callback.data.split(":", 2)[2]  # type: ignore[union-attr]

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("edit_reply_markup failed on link:remind (likely already removed)")

    await state.update_data({_ITEM_ID_KEY: item_id, _ATTEMPTS_KEY: 0})
    await state.set_state(ReminderStates.waiting_for_time)
    await callback.message.answer(t("reminder_prompt_when", lang))
