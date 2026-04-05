import logging
import re

from aiogram import F, Router
from aiogram.types import Message

from bot.services.classifier import ClassifierService, MessageType
from bot.services.link_service import LinkService

logger = logging.getLogger(__name__)

router = Router(name="messages")

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _extract_url(text: str) -> str | None:
    """Return the first URL found in text, or None."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Handle incoming photo — route to media pipeline (stub)."""
    logger.info("Received photo from user %s", message.from_user.id if message.from_user else "?")
    await message.answer("Фото получено. Обработка медиа скоро будет доступна.")


@router.message(F.document)
async def handle_document(message: Message) -> None:
    """Handle incoming document/file — route to media pipeline (stub)."""
    logger.info(
        "Received document from user %s", message.from_user.id if message.from_user else "?"
    )
    await message.answer("Файл получен. Обработка медиа скоро будет доступна.")


@router.message(F.text)
async def handle_text(
    message: Message,
    classifier: ClassifierService | None = None,
    link_service: LinkService | None = None,
) -> None:
    """Route incoming text to the correct pipeline based on AI classification."""
    text = message.text or ""
    is_forwarded = message.forward_origin is not None
    user_id = message.from_user.id if message.from_user else 0
    logger.info("Received text from user %s (forwarded=%s): %.80s", user_id, is_forwarded, text)

    if classifier is None:
        # Services not yet wired (early issues / tests without DI)
        await message.answer("Сообщение получено. Классификация скоро будет доступна.")
        return

    msg_type = await classifier.classify(text, has_media=False)

    if msg_type == MessageType.LINK and link_service is not None:
        url = _extract_url(text) or text
        from bot.handlers.links import handle_link_message

        await handle_link_message(message, url, link_service)
    else:
        # Stubs for task/note/idea pipelines (implemented in later issues)
        await message.answer(
            f"Тип: <b>{msg_type.value}</b>. Полная обработка будет добавлена позже."
        )
