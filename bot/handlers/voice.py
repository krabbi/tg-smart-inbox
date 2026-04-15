"""Handler for incoming voice messages — transcribe then route through classifier."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.exceptions import TranscriptionError
from bot.handlers.ideas import _COMPLEXITY_LABEL, _EFFORT_LABEL
from bot.handlers.links import handle_link_message
from bot.handlers.messages import _handle_task_with_time
from bot.handlers.reminders import task_remind_keyboard
from bot.services.classifier import ClassifierService, MessageType
from bot.services.idea_service import IdeaService
from bot.services.link_service import LinkService
from bot.services.note_service import NoteService
from bot.services.reminder_service import ReminderService
from bot.services.task_service import TaskService
from bot.services.time_parser import TimeParser
from bot.services.transcription_service import TranscriptionService
from bot.services.user_settings_service import UserSettingsService
from bot.utils.text import extract_url, has_time_expression

logger = logging.getLogger(__name__)

router = Router(name="voice")


@router.message(F.voice)
async def handle_voice(
    message: Message,
    state: FSMContext,
    transcription_service: TranscriptionService | None = None,
    classifier: ClassifierService | None = None,
    link_service: LinkService | None = None,
    idea_service: IdeaService | None = None,
    task_service: TaskService | None = None,
    note_service: NoteService | None = None,
    time_parser: TimeParser | None = None,
    reminder_service: ReminderService | None = None,
    user_settings_service: UserSettingsService | None = None,
) -> None:
    """Download voice message, transcribe it, then route through the classifier pipeline."""
    if transcription_service is None:
        await message.answer(
            "Голосовые сообщения не настроены.\n"
            "Добавь <code>GROQ_API_KEY</code> в конфигурацию (бесплатно: console.groq.com)."
        )
        return

    voice = message.voice  # type: ignore[union-attr]
    file = await message.bot.get_file(voice.file_id)  # type: ignore[union-attr]
    file_bytes_io = await message.bot.download_file(file.file_path)  # type: ignore[union-attr]
    audio_bytes = file_bytes_io.read()  # type: ignore[union-attr]

    try:
        transcript = await transcription_service.transcribe(audio_bytes)
    except TranscriptionError as exc:
        logger.warning(
            "Transcription failed for user %s: %s",
            message.from_user and message.from_user.id,
            exc,
        )
        # exc carries a user-facing message prepared by TranscriptionService
        await message.answer(str(exc))
        return

    await message.answer(f"🎤 Распознал: <i>«{transcript}»</i>")

    if classifier is None:
        return

    user_id = message.from_user.id if message.from_user else 0
    msg_type = await classifier.classify(transcript, has_media=False)

    if msg_type == MessageType.LINK and link_service is not None:
        url = extract_url(transcript) or transcript
        await handle_link_message(message, url, link_service)
    elif msg_type == MessageType.IDEA and idea_service is not None:
        try:
            saved = await idea_service.save_idea(transcript, user_id)
        except Exception:
            logger.exception("Idea save failed for user %s", user_id)
            await message.answer("Не удалось сохранить идею. Попробуй ещё раз.")
            return
        reply = "💡 Идея сохранена!"
        meta = []
        if saved.idea.complexity:
            meta.append(_COMPLEXITY_LABEL[saved.idea.complexity])
        if saved.idea.effort:
            meta.append(_EFFORT_LABEL[saved.idea.effort])
        if meta:
            reply += f" ({', '.join(meta)})"
        tags_str = " ".join(f"#{t}" for t in saved.idea.tags) if saved.idea.tags else ""
        if tags_str:
            reply += f"\n{tags_str}"
        await message.answer(reply)
    elif msg_type == MessageType.TASK and task_service is not None:
        try:
            saved = await task_service.save(transcript, user_id)
        except Exception:
            logger.exception("Task save failed for user %s", user_id)
            await message.answer("Не удалось сохранить задачу. Попробуй ещё раз.")
            return
        try:
            if has_time_expression(transcript):
                user_tz = "UTC"
                if user_settings_service is not None and user_id:
                    user_tz = await user_settings_service.get_timezone(user_id)
                await _handle_task_with_time(
                    message=message,
                    text=transcript,
                    item_id=str(saved.item.id),
                    state=state,
                    time_parser=time_parser,
                    reminder_service=reminder_service,
                    user_tz=user_tz,
                )
            else:
                await message.answer(
                    "✅ Задача сохранена!",
                    reply_markup=task_remind_keyboard(str(saved.item.id)),
                )
        except Exception:
            logger.exception("Failed to handle task reminder for user %s", user_id)
            await message.answer("Задача сохранена, но не удалось запустить диалог напоминания.")
    elif msg_type == MessageType.NOTE and note_service is not None:
        try:
            await note_service.save(transcript, user_id)
        except Exception:
            logger.exception("Note save failed for user %s", user_id)
            await message.answer("Не удалось сохранить заметку. Попробуй ещё раз.")
            return
        await message.answer("📝 Заметка сохранена!")
    else:
        await message.answer("Голосовое сообщение сохранено!")
