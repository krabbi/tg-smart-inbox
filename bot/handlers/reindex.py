"""Inline-button handler for retrying embedding generation on a single record."""

import logging
import uuid

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.i18n import t
from bot.services.reindex_service import ReindexResult, ReindexService

logger = logging.getLogger(__name__)

router = Router(name="reindex")

# Callback data layout: ``reindex:<kind>:<uuid>`` where ``<kind>`` is ``item`` or
# ``idea``. The whole string is at most ``"reindex:idea:"`` (13 bytes) plus a
# 36-char UUID = 49 bytes, well within Telegram's 64-byte callback_data limit.
_CB_PREFIX = "reindex:"
_CB_ITEM = "reindex:item:{record_id}"
_CB_IDEA = "reindex:idea:{record_id}"

_KIND_ITEM = "item"
_KIND_IDEA = "idea"


def retry_keyboard(kind: str, record_id: uuid.UUID | str, lang: str) -> InlineKeyboardMarkup:
    """Build the single-button keyboard offering to retry embedding generation."""
    if kind == _KIND_IDEA:
        callback_data = _CB_IDEA.format(record_id=record_id)
    else:
        callback_data = _CB_ITEM.format(record_id=record_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("reindex.button.try_again", lang),
                    callback_data=callback_data,
                ),
            ]
        ]
    )


def item_retry_keyboard(item_id: uuid.UUID | str, lang: str) -> InlineKeyboardMarkup:
    """Shortcut for an Item-flavoured retry keyboard."""
    return retry_keyboard(_KIND_ITEM, item_id, lang)


def idea_retry_keyboard(idea_id: uuid.UUID | str, lang: str) -> InlineKeyboardMarkup:
    """Shortcut for an Idea-flavoured retry keyboard."""
    return retry_keyboard(_KIND_IDEA, idea_id, lang)


def _parse_callback(data: str) -> tuple[str, uuid.UUID] | None:
    """Return ``(kind, record_id)`` parsed from callback data, or ``None`` if malformed."""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "reindex":
        return None
    kind = parts[1]
    if kind not in (_KIND_ITEM, _KIND_IDEA):
        return None
    try:
        record_id = uuid.UUID(parts[2])
    except ValueError:
        return None
    return kind, record_id


@router.callback_query(lambda c: c.data and c.data.startswith(_CB_PREFIX))
async def handle_reindex_one(
    callback: CallbackQuery,
    reindex_service: ReindexService | None = None,
    lang: str = "en",
) -> None:
    """Retry embedding generation for a single Item or Idea owned by the caller."""
    if callback.from_user is None or callback.message is None or callback.data is None:
        await callback.answer()
        return

    parsed = _parse_callback(callback.data)
    if parsed is None:
        logger.warning("Malformed reindex callback data: %r", callback.data)
        await callback.answer()
        return

    if reindex_service is None:
        await callback.answer(t("reindex.all.not_configured", lang), show_alert=True)
        return

    kind, record_id = parsed
    user_id = callback.from_user.id

    if kind == _KIND_IDEA:
        result = await reindex_service.reindex_idea(record_id, user_id)
    else:
        result = await reindex_service.reindex_item(record_id, user_id)

    if result is ReindexResult.NOT_FOUND:
        # Do not edit the message — the row may belong to a different user and
        # leaking an "indexed" state into their chat history would be confusing.
        await callback.answer(t("reindex.one.not_yours", lang), show_alert=True)
        return

    if result is ReindexResult.ALREADY_INDEXED:
        await callback.answer(t("reindex.one.already_indexed", lang), show_alert=True)
        await _replace_with_text(callback, t("reindex.one.success", lang))
        return

    if result is ReindexResult.SERVICE_UNAVAILABLE:
        await callback.answer()
        await _replace_with_text(
            callback,
            t("reindex.one.still_unavailable", lang),
            keyboard=retry_keyboard(kind, record_id, lang),
        )
        return

    # SUCCESS
    await callback.answer()
    await _replace_with_text(callback, t("reindex.one.success", lang))


async def _replace_with_text(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit the notice in place, falling back to a fresh message when the edit fails.

    Telegram refuses ``edit_message_text`` once the message is older than 48 hours
    (or when the same content is re-sent). In both cases we still want the user
    to see the result, so on failure we post a brand-new message in the chat.
    """
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        logger.debug("edit_text failed on reindex callback; sending fresh message")
        try:
            await callback.message.answer(text, reply_markup=keyboard)
        except Exception:
            logger.exception("Failed to send reindex result message")
