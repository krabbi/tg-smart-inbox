from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Config
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.repositories.reminder_repository import ReminderRepository
from bot.repositories.user_settings import UserSettingsRepository
from bot.services.classifier import ClassifierService
from bot.services.claude_client import ClaudeClient
from bot.services.drive_service import DriveService
from bot.services.embedding_service import EmbeddingService
from bot.services.idea_service import IdeaService
from bot.services.link_service import LinkService
from bot.services.list_service import ListService
from bot.services.media_service import MediaService
from bot.services.note_service import NoteService
from bot.services.reindex_service import ReindexService
from bot.services.reminder_service import ReminderService
from bot.services.scraper import Scraper
from bot.services.semantic_search_service import SemanticSearchService
from bot.services.task_service import TaskService
from bot.services.time_parser import TimeParser
from bot.services.transcription_service import TranscriptionService
from bot.services.user_settings_service import DEFAULT_LANGUAGE, UserSettingsService
from bot.services.vision_service import VisionService


def _extract_user_id(event: TelegramObject) -> int | None:
    """Return the Telegram user id from an update/message/callback, or None if absent."""
    if isinstance(event, Update):
        if event.message and event.message.from_user:
            return event.message.from_user.id
        if event.callback_query and event.callback_query.from_user:
            return event.callback_query.from_user.id
        return None
    if isinstance(event, Message) and event.from_user:
        return event.from_user.id
    if isinstance(event, CallbackQuery) and event.from_user:
        return event.from_user.id
    return None


class DependencyMiddleware(BaseMiddleware):
    """Inject per-request services and DB session into handler data on every update."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config: Config) -> None:
        self._factory = session_factory
        self._config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Open a DB session, build and inject all services, then call the handler."""
        async with self._factory() as session:
            data["session"] = session
            data["config"] = self._config

            claude = ClaudeClient(self._config)
            embedding_service = EmbeddingService(self._config)
            item_repo = ItemRepository(session)
            reminder_repo = ReminderRepository(session)
            idea_repo = IdeaRepository(session)

            data["classifier"] = ClassifierService(claude)
            data["embedding_service"] = embedding_service
            data["link_service"] = LinkService(
                session=session,
                item_repo=item_repo,
                scraper=Scraper(),
                claude=claude,
                embedding_service=embedding_service,
            )
            data["reminder_service"] = ReminderService(
                session=session, repo=reminder_repo, item_repo=item_repo
            )
            data["time_parser"] = TimeParser(claude)
            data["idea_service"] = IdeaService(
                session,
                item_repo,
                idea_repo,
                claude,
                embedding_service=embedding_service,
            )
            data["task_service"] = TaskService(
                session, item_repo, embedding_service=embedding_service
            )
            data["note_service"] = NoteService(
                session, item_repo, embedding_service=embedding_service
            )
            data["list_service"] = ListService(item_repo=item_repo)
            data["semantic_search_service"] = SemanticSearchService(
                embedding_service=embedding_service,
                item_repo=item_repo,
                idea_repo=idea_repo,
            )
            data["reindex_service"] = ReindexService(
                embedding_service=embedding_service,
                item_repository=item_repo,
                idea_repository=idea_repo,
                session=session,
            )
            user_settings_service = UserSettingsService(
                session=session, repo=UserSettingsRepository(session)
            )
            data["user_settings_service"] = user_settings_service

            # Resolve the caller's language once per update and inject it as ``lang``
            # so every handler can localize its reply via ``t(key, lang)``. Fall back
            # to the default language when no user context is available or settings
            # are missing (e.g. first-time users).
            user_id = _extract_user_id(event)
            if user_id is not None:
                data["lang"] = await user_settings_service.get_language(user_id)
            else:
                data["lang"] = DEFAULT_LANGUAGE

            # Whisper transcription — only available when Groq key is configured
            if self._config.groq_api_key:
                data["transcription_service"] = TranscriptionService(self._config)
            else:
                data["transcription_service"] = None

            # Drive-dependent services are only available when credentials are configured
            if self._config.google_drive_folder_id:
                drive = DriveService(self._config)
                vision = VisionService(self._config)
                data["media_service"] = MediaService(session, item_repo, vision, drive)
            else:
                data["media_service"] = None

            # Make reminder_repo available for scheduler
            data["reminder_repo"] = reminder_repo

            return await handler(event, data)
