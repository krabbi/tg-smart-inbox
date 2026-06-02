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
        """Pass through allowed users; silently drop all others.

        Anonymous events (no ``from_user``) are always dropped, regardless of
        whether an allowlist is configured, because every subsequent handler
        requires a valid ``user_id`` to scope DB operations correctly.
        """
        user_id = self._extract_user_id(event)
        if self._allowed:
            # Allowlist mode: only listed user IDs may proceed.
            if user_id is None or user_id not in self._allowed:
                return None
        else:
            # Open mode: any authenticated user may proceed, but anonymous
            # events (channel posts, etc.) are still silently discarded.
            if user_id is None:
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
