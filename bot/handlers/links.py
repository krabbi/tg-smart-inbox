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


async def handle_link_message(message: Message, url: str, link_service: LinkService) -> None:
    """Save a link and show action buttons. Called from the messages handler."""
    user_id = message.from_user.id if message.from_user else 0
    item = await link_service.save(url, user_id)
    keyboard = _link_keyboard(str(item.id))
    await message.answer(f"🔗 Ссылка сохранена:\n{url}", reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith("link:summary:"))
async def cb_link_summary(callback: CallbackQuery, link_service: LinkService) -> None:
    """Handle [Саммари] button — fetch page and show Claude summary."""
    item_id = callback.data.split(":", 2)[2]  # type: ignore[union-attr]
    url = callback.message.text.split("\n")[-1] if callback.message else ""  # type: ignore[union-attr]

    await callback.answer("Загружаю страницу...")
    try:
        summary = await link_service.summarize(url)
        text = f"📋 <b>{html.escape(summary.title)}</b>\n\n{html.escape(summary.summary)}"
        if summary.takeaways:
            text += "\n\n<b>Ключевые моменты:</b>\n" + "\n".join(
                f"• {html.escape(t)}" for t in summary.takeaways
            )
        await callback.message.edit_text(text, parse_mode="HTML")  # type: ignore[union-attr]
    except ScrapingError as exc:
        logger.warning("Scraping failed for item %s: %s", item_id, exc)
        await callback.message.edit_text("❌ Не удалось загрузить страницу.")  # type: ignore[union-attr]


@router.callback_query(lambda c: c.data and c.data.startswith("link:save:"))
async def cb_link_save(callback: CallbackQuery) -> None:
    """Handle [Сохранить] button — confirm save."""
    await callback.answer("✅ Сохранено!")
    await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]


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
