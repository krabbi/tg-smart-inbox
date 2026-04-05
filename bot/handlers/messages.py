import logging

from aiogram import F, Router
from aiogram.types import Message

logger = logging.getLogger(__name__)

router = Router(name="messages")


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
async def handle_text(message: Message) -> None:
    """Handle incoming text message — route to classifier pipeline (stub)."""
    # Forwarded messages arrive with forward_origin set; content type is unchanged.
    is_forwarded = message.forward_origin is not None
    user_id = message.from_user.id if message.from_user else "?"
    logger.info(
        "Received text from user %s (forwarded=%s): %.80s",
        user_id,
        is_forwarded,
        message.text,
    )
    await message.answer("Сообщение получено. Классификация скоро будет доступна.")
