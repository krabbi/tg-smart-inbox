from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Config
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.repositories.reminder_repository import ReminderRepository
from bot.services.classifier import ClassifierService
from bot.services.claude_client import ClaudeClient
from bot.services.drive_service import DriveService
from bot.services.idea_service import IdeaService
from bot.services.link_service import LinkService
from bot.services.list_service import ListService
from bot.services.media_service import MediaService
from bot.services.reminder_service import ReminderService
from bot.services.scraper import Scraper
from bot.services.time_parser import TimeParser
from bot.services.transcription_service import TranscriptionService
from bot.services.vision_service import VisionService


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
            item_repo = ItemRepository(session)
            reminder_repo = ReminderRepository(session)
            idea_repo = IdeaRepository(session)

            data["classifier"] = ClassifierService(claude)
            data["link_service"] = LinkService(
                session=session, item_repo=item_repo, scraper=Scraper(), claude=claude
            )
            data["reminder_service"] = ReminderService(session=session, repo=reminder_repo)
            data["time_parser"] = TimeParser(claude)
            data["idea_service"] = IdeaService(session, item_repo, idea_repo, claude)
            data["list_service"] = ListService(item_repo=item_repo)

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
