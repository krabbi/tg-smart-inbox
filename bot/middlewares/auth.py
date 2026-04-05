from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.config import Config


class AuthMiddleware(BaseMiddleware):
    """Silently reject messages from users not in ALLOWED_USER_IDS."""

    def __init__(self, config: Config) -> None:
        self._allowed = set(config.allowed_user_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Pass through allowed users; silently drop all others."""
        if self._allowed:
            user_id = self._extract_user_id(event)
            if user_id is None or user_id not in self._allowed:
                return None
        return await handler(event, data)

    @staticmethod
    def _extract_user_id(event: TelegramObject) -> int | None:
        """Extract Telegram user ID from any event type."""
        if isinstance(event, Message):
            return event.from_user.id if event.from_user else None
        # For CallbackQuery, InlineQuery etc — access via .from_user
        user = getattr(event, "from_user", None)
        return user.id if user else None
