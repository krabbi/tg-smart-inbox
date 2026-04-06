import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.ideas import _COMPLEXITY_LABEL, _EFFORT_LABEL
from bot.handlers.reminders import ask_reminder
from bot.services.classifier import ClassifierService, MessageType
from bot.services.idea_service import IdeaService
from bot.services.link_service import LinkService
from bot.services.media_service import MediaService
from bot.services.note_service import NoteService
from bot.services.task_service import TaskService
from bot.utils.text import extract_url

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


@router.message(F.text)
async def handle_text(
    message: Message,
    state: FSMContext,
    classifier: ClassifierService | None = None,
    link_service: LinkService | None = None,
    idea_service: IdeaService | None = None,
    task_service: TaskService | None = None,
    note_service: NoteService | None = None,
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
            saved = await task_service.save(text, user_id)
        except Exception:
            logger.exception("Task save failed for user %s", user_id)
            await message.answer("Не удалось сохранить задачу. Попробуй ещё раз.")
            return
        try:
            await ask_reminder(
                message=message, task_text=text, item_id=str(saved.item.id), state=state
            )
        except Exception:
            logger.exception("Failed to start reminder dialog for user %s", user_id)
            await message.answer("Задача сохранена, но не удалось запустить диалог напоминания.")
    elif msg_type == MessageType.NOTE and note_service is not None:
        try:
            await note_service.save(text, user_id)
        except Exception:
            logger.exception("Note save failed for user %s", user_id)
            await message.answer("Не удалось сохранить заметку. Попробуй ещё раз.")
            return
        await message.answer("📝 Заметка сохранена!")
    else:
        await message.answer(
            f"Тип: <b>{msg_type.value}</b>. Полная обработка будет добавлена позже."
        )
