from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Message, User

from bot.config import Config
from bot.middlewares.auth import AuthMiddleware


def make_message(user_id: int) -> Message:
    """Create a minimal mock Message with the given user_id."""
    user = MagicMock(spec=User)
    user.id = user_id
    message = MagicMock(spec=Message)
    message.from_user = user
    return message


async def test_allowed_user_passes_through() -> None:
    config = Config(
        telegram_bot_token="fake-token",
        anthropic_api_key="sk-ant-fake",
        allowed_user_ids=[111, 222],
    )
    middleware = AuthMiddleware(config)
    handler = AsyncMock(return_value="ok")
    message = make_message(111)

    result = await middleware(handler, message, {})

    handler.assert_awaited_once_with(message, {})
    assert result == "ok"


async def test_unknown_user_is_blocked() -> None:
    config = Config(
        telegram_bot_token="fake-token",
        anthropic_api_key="sk-ant-fake",
        allowed_user_ids=[111],
    )
    middleware = AuthMiddleware(config)
    handler = AsyncMock()
    message = make_message(999)

    result = await middleware(handler, message, {})

    handler.assert_not_awaited()
    assert result is None


async def test_empty_allowed_list_passes_everyone() -> None:
    config = Config(
        telegram_bot_token="fake-token",
        anthropic_api_key="sk-ant-fake",
        allowed_user_ids=[],
    )
    middleware = AuthMiddleware(config)
    handler = AsyncMock(return_value="ok")
    message = make_message(12345)

    result = await middleware(handler, message, {})

    handler.assert_awaited_once()
    assert result == "ok"


async def test_message_without_user_is_blocked() -> None:
    config = Config(
        telegram_bot_token="fake-token",
        anthropic_api_key="sk-ant-fake",
        allowed_user_ids=[111],
    )
    middleware = AuthMiddleware(config)
    handler = AsyncMock()
    message = MagicMock(spec=Message)
    message.from_user = None

    result = await middleware(handler, message, {})

    handler.assert_not_awaited()
    assert result is None


def test_extract_user_id_from_message() -> None:
    message = make_message(42)
    assert AuthMiddleware._extract_user_id(message) == 42


def test_extract_user_id_from_message_without_user() -> None:
    message = MagicMock(spec=Message)
    message.from_user = None
    assert AuthMiddleware._extract_user_id(message) is None


def test_extract_user_id_from_non_message_event() -> None:
    event = MagicMock()
    event.from_user = MagicMock()
    event.from_user.id = 77
    assert AuthMiddleware._extract_user_id(event) == 77
