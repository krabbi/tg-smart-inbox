import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.exceptions import TimeParseError
from bot.handlers.ideas import _COMPLEXITY_LABEL, _EFFORT_LABEL
from bot.handlers.reminders import (
    _ATTEMPTS_KEY,
    _ITEM_ID_KEY,
    ReminderStates,
    task_remind_keyboard,
)
from bot.services.classifier import ClassifierService, MessageType
from bot.services.idea_service import IdeaService
from bot.services.link_service import LinkService
from bot.services.media_service import MediaService
from bot.services.note_service import NoteService
from bot.services.reminder_service import ReminderService
from bot.services.task_service import TaskService
from bot.services.time_parser import TimeParser
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
) -> None:
    """Handle incoming photo — categorize with Vision, upload to Drive."""
    if media_service is None:
        logger.warning("media_service not injected — DI misconfiguration")
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
        logger.warning("media_service not injected — DI misconfiguration")
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


async def _handle_task_with_time(
    message: Message,
    text: str,
    item_id: str,
    state: FSMContext,
    time_parser: TimeParser | None,
    reminder_service: ReminderService | None,
) -> None:
    """Try to auto-parse time from task text and create reminder; fall back to FSM on failure."""
    if time_parser is None or reminder_service is None:
        # Cannot auto-parse — show remind button as fallback
        await message.answer(
            "\u2705 Задача сохранена!",
            reply_markup=task_remind_keyboard(item_id),
        )
        return

    from datetime import UTC, datetime

    try:
        remind_at = await time_parser.parse(text, now=datetime.now(UTC))
    except TimeParseError:
        # Could not auto-parse — enter FSM for manual time input
        await state.update_data({_ITEM_ID_KEY: item_id, _ATTEMPTS_KEY: 0})
        await state.set_state(ReminderStates.waiting_for_time)
        await message.answer(
            "\u2705 Задача сохранена! Уточни время напоминания "
            "(или отправь то же выражение ещё раз):\n"
            "Для отмены — /cancel"
        )
        return

    import uuid

    try:
        await reminder_service.create(item_id=uuid.UUID(item_id), remind_at=remind_at)
    except Exception:
        logger.exception("Failed to auto-create reminder for item %s", item_id)
        await message.answer(
            "\u2705 Задача сохранена, но не удалось создать напоминание.",
            reply_markup=task_remind_keyboard(item_id),
        )
        return

    formatted = remind_at.strftime("%d.%m.%Y %H:%M UTC")
    await message.answer(f"\u2705 Задача сохранена!\n\U0001f514 Напомню {formatted}!")


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
) -> None:
    """Route incoming text to the correct pipeline based on AI classification."""
    text = message.text or ""
    is_forwarded = message.forward_origin is not None
    user_id = message.from_user.id if message.from_user else 0
    logger.info("Received text from user %s (forwarded=%s): %.80s", user_id, is_forwarded, text)

    if classifier is None:
        await message.answer("Сообщение получено. Классификация скоро будет доступна.")
        return

    # Fast path: suggestion queries bypass the classifier
    if _is_suggestion_query(text) and idea_service is not None:
        suggestion = await idea_service.suggest(user_id, text)
        await message.answer(suggestion)
        return

    msg_type = await classifier.classify(text, has_media=False)

    if msg_type == MessageType.LINK and link_service is not None:
        url = extract_url(text) or text
        from bot.handlers.links import handle_link_message

        await handle_link_message(message, url, link_service)
    elif msg_type == MessageType.IDEA and idea_service is not None:
        try:
            saved = await idea_service.save_idea(text, user_id)
        except Exception:
            logger.exception("Idea save failed for user %s", user_id)
            await message.answer("Не удалось сохранить идею. Попробуй ещё раз.")
            return
        reply = "\U0001f4a1 Идея сохранена!"
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
            saved = await task_service.save(text, user_id)
        except Exception:
            logger.exception("Task save failed for user %s", user_id)
            await message.answer("Не удалось сохранить задачу. Попробуй ещё раз.")
            return
        try:
            if has_time_expression(text):
                await _handle_task_with_time(
                    message=message,
                    text=text,
                    item_id=str(saved.item.id),
                    state=state,
                    time_parser=time_parser,
                    reminder_service=reminder_service,
                )
            else:
                # No time expression — save without dialog, offer remind button
                await message.answer(
                    "\u2705 Задача сохранена!",
                    reply_markup=task_remind_keyboard(str(saved.item.id)),
                )
        except Exception:
            logger.exception("Failed to handle task reminder for user %s", user_id)
            await message.answer("Задача сохранена, но не удалось запустить диалог напоминания.")
    elif msg_type == MessageType.NOTE and note_service is not None:
        try:
            await note_service.save(text, user_id)
        except Exception:
            logger.exception("Note save failed for user %s", user_id)
            await message.answer("Не удалось сохранить заметку. Попробуй ещё раз.")
            return
        await message.answer("\U0001f4dd Заметка сохранена!")
    else:
        await message.answer(
            f"Тип: <b>{msg_type.value}</b>. Полная обработка будет добавлена позже."
        )
