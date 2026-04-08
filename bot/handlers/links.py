import html
import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.exceptions import ScrapingError
from bot.handlers.reminders import _ATTEMPTS_KEY, _ITEM_ID_KEY, ReminderStates
from bot.services.link_service import LinkService

logger = logging.getLogger(__name__)

router = Router(name="links")

_CB_SUMMARY = "link:summary:{item_id}"
_CB_SAVE = "link:save:{item_id}"
_CB_REMIND = "link:remind:{item_id}"
_CB_RETRY = "link:retry:{item_id}"


def _link_keyboard(item_id: str) -> InlineKeyboardMarkup:
    """Build the action keyboard shown after a link is saved."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Саммари",
                    callback_data=_CB_SUMMARY.format(item_id=item_id),
                ),
                InlineKeyboardButton(
                    text="🔖 Сохранить",
                    callback_data=_CB_SAVE.format(item_id=item_id),
                ),
                InlineKeyboardButton(
                    text="⏰ Напомнить",
                    callback_data=_CB_REMIND.format(item_id=item_id),
                ),
            ]
        ]
    )


def _save_keyboard(item_id: str) -> InlineKeyboardMarkup:
    """Build keyboard with save button shown after summary is ready."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔖 Сохранить",
                    callback_data=_CB_SAVE.format(item_id=item_id),
                ),
            ]
        ]
    )


def _retry_keyboard(item_id: str) -> InlineKeyboardMarkup:
    """Build keyboard with retry button shown on summarization error."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Попробовать снова",
                    callback_data=_CB_RETRY.format(item_id=item_id),
                ),
            ]
        ]
    )


def _extract_url(message_text: str) -> str:
    """Extract URL from the saved-link message text."""
    return message_text.split("\n")[-1].strip()


async def handle_link_message(message: Message, url: str, link_service: LinkService) -> None:
    """Save a link and show action buttons. Called from the messages handler."""
    user_id = message.from_user.id if message.from_user else 0
    item = await link_service.save(url, user_id)
    keyboard = _link_keyboard(str(item.id))
    await message.answer(f"🔗 Ссылка сохранена:\n{url}", reply_markup=keyboard)


async def _do_summarize(
    callback: CallbackQuery, item_id: str, url: str, link_service: LinkService
) -> None:
    """Run the summarize flow: show loading, fetch summary, update message."""
    # Show loading state immediately, preserving URL
    await callback.message.edit_text(  # type: ignore[union-attr]
        f"🔗 {url}\n\n⏳ Загружаю саммари...",
        reply_markup=None,
    )

    try:
        summary = await link_service.summarize(url)
        text = (
            f"🔗 {html.escape(url)}\n\n"
            f"📋 <b>{html.escape(summary.title)}</b>\n\n"
            f"{html.escape(summary.body)}"
        )
        keyboard = _save_keyboard(item_id)
        await callback.message.edit_text(  # type: ignore[union-attr]
            text, parse_mode="HTML", reply_markup=keyboard
        )
    except ScrapingError as exc:
        logger.warning("Scraping failed for item %s: %s", item_id, exc)
        keyboard = _retry_keyboard(item_id)
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"🔗 {url}\n\n❌ Не удалось загрузить страницу.",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Unexpected error summarising item %s", item_id)
        keyboard = _retry_keyboard(item_id)
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"🔗 {url}\n\n❌ Не удалось получить саммари.",
            reply_markup=keyboard,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("link:summary:"))
async def cb_link_summary(callback: CallbackQuery, link_service: LinkService) -> None:
    """Handle [Саммари] button — fetch page and show Claude summary."""
    item_id = callback.data.split(":", 2)[2]  # type: ignore[union-attr]
    url = _extract_url(callback.message.text) if callback.message else ""  # type: ignore[union-attr]

    await callback.answer()
    await _do_summarize(callback, item_id, url, link_service)


@router.callback_query(lambda c: c.data and c.data.startswith("link:retry:"))
async def cb_link_retry(callback: CallbackQuery, link_service: LinkService) -> None:
    """Handle [Попробовать снова] button — retry summarization."""
    item_id = callback.data.split(":", 2)[2]  # type: ignore[union-attr]
    # URL is on the first line after the emoji prefix
    url = _extract_url_from_status_message(callback.message.text) if callback.message else ""  # type: ignore[union-attr]

    await callback.answer()
    await _do_summarize(callback, item_id, url, link_service)


def _extract_url_from_status_message(text: str) -> str:
    """Extract URL from a status message (loading/error) where first line is '🔗 <url>'."""
    first_line = text.split("\n")[0].strip()
    # Remove the link emoji prefix
    if first_line.startswith("🔗 "):
        return first_line[len("🔗 ") :]
    return first_line


@router.callback_query(lambda c: c.data and c.data.startswith("link:save:"))
async def cb_link_save(callback: CallbackQuery) -> None:
    """Handle [Сохранить] button — confirm save with persistent text."""
    await callback.answer()
    if callback.message is None:
        return
    existing_text = callback.message.html_text or callback.message.text or ""
    await callback.message.edit_text(
        existing_text + "\n\n🔖 <i>Сохранено</i>",
        parse_mode="HTML",
        reply_markup=None,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("link:remind:"))
async def cb_link_remind(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle [⏰ Напомнить] button — go directly to time input, skip yes/no confirmation."""
    await callback.answer()
    if callback.message is None:
        return

    item_id = callback.data.split(":", 2)[2]  # type: ignore[union-attr]

    await callback.message.edit_reply_markup(reply_markup=None)

    await state.update_data({_ITEM_ID_KEY: item_id, _ATTEMPTS_KEY: 0})
    await state.set_state(ReminderStates.waiting_for_time)
    await callback.message.answer(
        "Когда напомнить? (например: «завтра в 10», «через 2 часа», «в пятницу в 15:00»)\n"
        "Для отмены — /cancel"
    )
