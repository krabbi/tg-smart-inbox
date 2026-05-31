import logging
import re
import uuid
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.exceptions import TimeParseError
from bot.handlers.ideas import complexity_label, effort_label
from bot.handlers.links import handle_link_message
from bot.handlers.reindex import idea_retry_keyboard, item_retry_keyboard
from bot.handlers.reminders import (
    _ATTEMPTS_KEY,
    _ITEM_ID_KEY,
    ReminderStates,
    task_remind_keyboard,
)
from bot.i18n import t
from bot.services.classifier import ClassifierService, MessageType
from bot.services.idea_service import IdeaService
from bot.services.link_service import LinkService
from bot.services.media_service import MediaService
from bot.services.note_service import NoteService
from bot.services.reminder_service import ReminderService
from bot.services.task_service import TaskService
from bot.services.time_parser import TimeParser
from bot.services.user_settings_service import UserSettingsService
from bot.utils.datetime_utils import format_remind_at
from bot.utils.text import extract_url, has_time_expression

logger = logging.getLogger(__name__)

router = Router(name="messages")

# Detects free-form suggestion queries without a Claude API call
_SUGGESTION_RE = re.compile(
    r"(что|чем|куда|о\s*чём?)\s*(поделать|заняться|делать|почитать|порекомендуешь)"
    r"|give me an idea|what should (i|we) (do|work on)|suggest something",
    re.IGNORECASE,
)


def _is_suggestion_query(text: str) -> bool:
    """Return True if the text looks like a request for idea suggestions."""
    return bool(_SUGGESTION_RE.search(text))


@router.message(F.photo)
async def handle_photo(
    message: Message,
    media_service: MediaService | None = None,
    lang: str = "en",
) -> None:
    """Handle incoming photo — categorize with Vision, upload to Drive."""
    if media_service is None:
        logger.warning("media_service not injected — DI misconfiguration")
        await message.answer(t("photo_received_disabled", lang))
        return

    # AuthMiddleware drops anonymous messages, but guard explicitly so
    # ``user_id`` is never silently coerced to a placeholder before reaching
    # DriveService — that would mix Drive folders across users.
    if message.from_user is None:
        logger.warning("Photo received without from_user; dropping")
        return
    user_id = message.from_user.id
    photo = message.photo[-1]  # largest size
    file = await message.bot.get_file(photo.file_id)  # type: ignore[union-attr]
    file_bytes = await message.bot.download_file(file.file_path)  # type: ignore[union-attr]

    try:
        result = await media_service.process(
            file_bytes=file_bytes.read(),  # type: ignore[union-attr]
            filename=f"photo_{photo.file_id}.jpg",
            user_id=user_id,
            media_type="image/jpeg",
            lang=lang,
        )
        await message.answer(MediaService.format_reply(result, lang))
    except Exception:
        logger.exception("Media processing failed for user %s", user_id)
        await message.answer(t("photo_process_failed", lang))


@router.message(F.document)
async def handle_document(
    message: Message,
    media_service: MediaService | None = None,
    lang: str = "en",
) -> None:
    """Handle incoming document/file — categorize and upload to Drive."""
    if media_service is None:
        logger.warning("media_service not injected — DI misconfiguration")
        await message.answer(t("document_received_disabled", lang))
        return

    # AuthMiddleware drops anonymous messages, but guard explicitly so
    # ``user_id`` is never silently coerced to a placeholder before reaching
    # DriveService — that would mix Drive folders across users.
    if message.from_user is None:
        logger.warning("Document received without from_user; dropping")
        return
    user_id = message.from_user.id
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
            lang=lang,
        )
        await message.answer(MediaService.format_reply(result, lang))
    except Exception:
        logger.exception("Media processing failed for user %s", user_id)
        await message.answer(t("document_process_failed", lang))


async def _handle_task_with_time(
    message: Message,
    text: str,
    item_id: str,
    state: FSMContext,
    time_parser: TimeParser | None,
    reminder_service: ReminderService | None,
    lang: str,
    user_tz: str = "UTC",
) -> None:
    """Try to auto-parse time from task text and create reminder; fall back to FSM on failure."""
    if time_parser is None or reminder_service is None:
        # Cannot auto-parse — show remind button as fallback
        await message.answer(
            t("task_saved", lang),
            reply_markup=task_remind_keyboard(item_id, lang),
        )
        return

    try:
        remind_at = await time_parser.parse(text, now=datetime.now(UTC), user_tz=user_tz)
    except TimeParseError:
        # Could not auto-parse — enter FSM for manual time input
        await state.update_data({_ITEM_ID_KEY: item_id, _ATTEMPTS_KEY: 0})
        await state.set_state(ReminderStates.waiting_for_time)
        await message.answer(t("task_clarify_time", lang))
        return

    try:
        await reminder_service.create(item_id=uuid.UUID(item_id), remind_at=remind_at)
    except Exception:
        logger.exception("Failed to auto-create reminder for item %s", item_id)
        await message.answer(
            t("task_saved_reminder_failed", lang),
            reply_markup=task_remind_keyboard(item_id, lang),
        )
        return

    formatted = format_remind_at(remind_at, user_tz)
    await message.answer(t("task_saved_with_reminder", lang, formatted=formatted))


def _format_idea_reply(saved, lang: str) -> str:
    """Format the confirmation reply for a freshly saved idea."""
    reply = t("idea_saved", lang)
    meta = []
    if saved.idea.complexity:
        meta.append(complexity_label(saved.idea.complexity, lang))
    if saved.idea.effort:
        meta.append(effort_label(saved.idea.effort, lang))
    if meta:
        reply += f" ({', '.join(meta)})"
    tags_str = " ".join(f"#{tag}" for tag in saved.idea.tags) if saved.idea.tags else ""
    if tags_str:
        reply += f"\n{tags_str}"
    return reply


@router.message(F.text)
async def handle_text(
    message: Message,
    state: FSMContext,
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
    """Route incoming text to the correct pipeline based on AI classification."""
    text = message.text or ""
    is_forwarded = message.forward_origin is not None
    user_id = message.from_user.id if message.from_user else 0
    logger.info("Received text from user %s (forwarded=%s): %.80s", user_id, is_forwarded, text)

    if classifier is None:
        await message.answer(t("classifier_unavailable", lang))
        return

    # Fast path: suggestion queries bypass the classifier
    if _is_suggestion_query(text) and idea_service is not None:
        suggestion = await idea_service.suggest(user_id, text, lang=lang)
        await message.answer(suggestion)
        return

    msg_type = await classifier.classify(text, has_media=False, lang=lang)

    if msg_type == MessageType.LINK and link_service is not None:
        url = extract_url(text) or text
        await handle_link_message(message, url, link_service, lang)
    elif msg_type == MessageType.IDEA and idea_service is not None:
        try:
            saved = await idea_service.save_idea(text, user_id, lang=lang)
        except Exception:
            logger.exception("Idea save failed for user %s", user_id)
            await message.answer(t("idea_save_failed", lang))
            return
        await message.answer(_format_idea_reply(saved, lang))
        if not saved.indexed:
            await message.answer(
                t("embedding_unavailable_notice", lang),
                reply_markup=idea_retry_keyboard(saved.idea.id, lang),
            )
    elif msg_type == MessageType.TASK and task_service is not None:
        try:
            saved = await task_service.save(text, user_id)
        except Exception:
            logger.exception("Task save failed for user %s", user_id)
            await message.answer(t("task_save_failed", lang))
            return
        try:
            if has_time_expression(text):
                user_tz = "UTC"
                if user_settings_service is not None and user_id:
                    user_tz = await user_settings_service.get_timezone(user_id)
                await _handle_task_with_time(
                    message=message,
                    text=text,
                    item_id=str(saved.item.id),
                    state=state,
                    time_parser=time_parser,
                    reminder_service=reminder_service,
                    lang=lang,
                    user_tz=user_tz,
                )
            else:
                # No time expression — save without dialog, offer remind button
                await message.answer(
                    t("task_saved", lang),
                    reply_markup=task_remind_keyboard(str(saved.item.id), lang),
                )
            if not saved.indexed:
                await message.answer(
                    t("embedding_unavailable_notice", lang),
                    reply_markup=item_retry_keyboard(saved.item.id, lang),
                )
        except Exception:
            logger.exception("Failed to handle task reminder for user %s", user_id)
            await message.answer(t("task_reminder_dialog_failed", lang))
    elif msg_type == MessageType.NOTE and note_service is not None:
        try:
            saved_note = await note_service.save(text, user_id)
        except Exception:
            logger.exception("Note save failed for user %s", user_id)
            await message.answer(t("note_save_failed", lang))
            return
        await message.answer(t("note_saved", lang))
        if not saved_note.indexed:
            await message.answer(
                t("embedding_unavailable_notice", lang),
                reply_markup=item_retry_keyboard(saved_note.item.id, lang),
            )
    else:
        await message.answer(t("unknown_type", lang, type=msg_type.value))
