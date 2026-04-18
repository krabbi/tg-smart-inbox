"""Handler for incoming voice messages — transcribe then route through classifier."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.exceptions import TranscriptionError
from bot.handlers.links import handle_link_message
from bot.handlers.messages import _format_idea_reply, _handle_task_with_time
from bot.handlers.reminders import task_remind_keyboard
from bot.i18n import t
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
    lang: str = "en",
) -> None:
    """Download voice message, transcribe it, then route through the classifier pipeline."""
    if transcription_service is None:
        await message.answer(t("voice_not_configured", lang))
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
        # ``exc`` carries an i18n key prepared by TranscriptionService — translate
        # it against the caller's language so the user sees a localized message.
        await message.answer(t(str(exc), lang))
        return

    await message.answer(t("voice_transcribed", lang, text=transcript))

    if classifier is None:
        return

    user_id = message.from_user.id if message.from_user else 0
    msg_type = await classifier.classify(transcript, has_media=False)

    if msg_type == MessageType.LINK and link_service is not None:
        url = extract_url(transcript) or transcript
        await handle_link_message(message, url, link_service, lang)
    elif msg_type == MessageType.IDEA and idea_service is not None:
        try:
            saved = await idea_service.save_idea(transcript, user_id)
        except Exception:
            logger.exception("Idea save failed for user %s", user_id)
            await message.answer(t("idea_save_failed", lang))
            return
        await message.answer(_format_idea_reply(saved, lang))
        if not saved.indexed:
            await message.answer(t("embedding_unavailable_notice", lang))
    elif msg_type == MessageType.TASK and task_service is not None:
        try:
            saved = await task_service.save(transcript, user_id)
        except Exception:
            logger.exception("Task save failed for user %s", user_id)
            await message.answer(t("task_save_failed", lang))
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
                    lang=lang,
                    user_tz=user_tz,
                )
            else:
                await message.answer(
                    t("task_saved", lang),
                    reply_markup=task_remind_keyboard(str(saved.item.id), lang),
                )
        except Exception:
            logger.exception("Failed to handle task reminder for user %s", user_id)
            await message.answer(t("task_reminder_dialog_failed", lang))
    elif msg_type == MessageType.NOTE and note_service is not None:
        try:
            await note_service.save(transcript, user_id)
        except Exception:
            logger.exception("Note save failed for user %s", user_id)
            await message.answer(t("note_save_failed", lang))
            return
        await message.answer(t("note_saved", lang))
    else:
        await message.answer(t("voice_fallback_saved", lang))
