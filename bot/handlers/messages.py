import logging
import re

from aiogram import F, Router
from aiogram.types import Message

from bot.services.classifier import ClassifierService, MessageType
from bot.services.link_service import LinkService
from bot.services.media_service import MediaService

logger = logging.getLogger(__name__)

router = Router(name="messages")

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _extract_url(text: str) -> str | None:
    """Return the first URL found in text, or None."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None


@router.message(F.photo)
async def handle_photo(
    message: Message,
    media_service: MediaService | None = None,
) -> None:
    """Handle incoming photo — categorize with Vision, upload to Drive."""
    if media_service is None:
        await message.answer("Фото получено. Обработка медиа скоро будет доступна.")
        return

    user_id = message.from_user.id if message.from_user else 0
    photo = message.photo[-1]  # largest size
    file = await message.bot.get_file(photo.file_id)  # type: ignore[union-attr]
    file_bytes = await message.bot.download_file(file.file_path)  # type: ignore[union-attr]

    try:
        result = await media_service.process(
            file_bytes=file_bytes.read(),  # type: ignore[union-attr]
            filename=f"photo_{photo.file_id}.jpg",
            user_id=user_id,
            media_type="image/jpeg",
        )
        await message.answer(MediaService.format_reply(result))
    except Exception:
        logger.exception("Media processing failed for user %s", user_id)
        await message.answer("Не удалось обработать фото. Попробуй ещё раз.")


@router.message(F.document)
async def handle_document(
    message: Message,
    media_service: MediaService | None = None,
) -> None:
    """Handle incoming document/file — categorize and upload to Drive."""
    if media_service is None:
        await message.answer("Файл получен. Обработка медиа скоро будет доступна.")
        return

    user_id = message.from_user.id if message.from_user else 0
    doc = message.document  # type: ignore[union-attr]
    file = await message.bot.get_file(doc.file_id)  # type: ignore[union-attr]
    file_bytes = await message.bot.download_file(file.file_path)  # type: ignore[union-attr]
    mime = doc.mime_type or "application/octet-stream"

    try:
        result = await media_service.process(
            file_bytes=file_bytes.read(),  # type: ignore[union-attr]
            filename=doc.file_name or f"file_{doc.file_id}",
            user_id=user_id,
            media_type=mime,
        )
        await message.answer(MediaService.format_reply(result))
    except Exception:
        logger.exception("Media processing failed for user %s", user_id)
        await message.answer("Не удалось обработать файл. Попробуй ещё раз.")


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
        await message.answer("Сообщение получено. Классификация скоро будет доступна.")
        return

    msg_type = await classifier.classify(text, has_media=False)

    if msg_type == MessageType.LINK and link_service is not None:
        url = _extract_url(text) or text
        from bot.handlers.links import handle_link_message

        await handle_link_message(message, url, link_service)
    else:
        await message.answer(
            f"Тип: <b>{msg_type.value}</b>. Полная обработка будет добавлена позже."
        )
