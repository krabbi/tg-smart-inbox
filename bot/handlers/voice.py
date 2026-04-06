"""Handler for incoming voice messages — transcribe then route through classifier."""

import logging

from aiogram import F, Router
from aiogram.types import Message

from bot.exceptions import TranscriptionError
from bot.handlers.links import handle_link_message
from bot.services.classifier import ClassifierService, MessageType
from bot.services.idea_service import IdeaService
from bot.services.link_service import LinkService
from bot.services.transcription_service import TranscriptionService

logger = logging.getLogger(__name__)

router = Router(name="voice")


@router.message(F.voice)
async def handle_voice(
    message: Message,
    transcription_service: TranscriptionService | None = None,
    classifier: ClassifierService | None = None,
    link_service: LinkService | None = None,
    idea_service: IdeaService | None = None,
) -> None:
    """Download voice message, transcribe it, then route through the classifier pipeline."""
    if transcription_service is None:
        await message.answer("Голосовые сообщения скоро будут поддерживаться.")
        return

    voice = message.voice  # type: ignore[union-attr]
    file = await message.bot.get_file(voice.file_id)  # type: ignore[union-attr]
    file_bytes_io = await message.bot.download_file(file.file_path)  # type: ignore[union-attr]
    audio_bytes = file_bytes_io.read()  # type: ignore[union-attr]

    try:
        transcript = await transcription_service.transcribe(audio_bytes)
    except TranscriptionError:
        logger.exception("Transcription failed for user %s", message.from_user and message.from_user.id)
        await message.answer("Не удалось распознать голосовое сообщение. Попробуй ещё раз.")
        return

    await message.answer(f"🎤 Распознал: <i>«{transcript}»</i>")

    if classifier is None:
        return

    user_id = message.from_user.id if message.from_user else 0
    msg_type = await classifier.classify(transcript, has_media=False)

    if msg_type == MessageType.LINK and link_service is not None:
        import re

        url_match = re.search(r"https?://\S+", transcript, re.IGNORECASE)
        url = url_match.group(0) if url_match else transcript
        await handle_link_message(message, url, link_service)
    elif msg_type == MessageType.IDEA and idea_service is not None:
        try:
            saved = await idea_service.save_idea(transcript, user_id)
        except Exception:
            logger.exception("Idea save failed for user %s", user_id)
            await message.answer("Не удалось сохранить идею. Попробуй ещё раз.")
            return
        tags_str = " ".join(f"#{t}" for t in saved.idea.tags) if saved.idea.tags else ""
        reply = "💡 Идея сохранена!"
        if tags_str:
            reply += f"\n{tags_str}"
        await message.answer(reply)
    else:
        await message.answer(
            f"Тип: <b>{msg_type.value}</b>. Полная обработка будет добавлена позже."
        )
