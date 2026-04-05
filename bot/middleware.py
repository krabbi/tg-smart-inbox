from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Config


class DependencyMiddleware(BaseMiddleware):
    """Inject config and DB session into handler data on every update.

    Future service instances (LinkService, ClassifierService, etc.) should be
    constructed here once their implementations exist and injected via data dict.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config: Config) -> None:
        self._factory = session_factory
        self._config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Open a DB session, inject deps, then call the handler."""
        async with self._factory() as session:
            data["session"] = session
            data["config"] = self._config
            return await handler(event, data)
