import pytest
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from bot.bot import create_bot, create_dispatcher
from bot.config import Config
from bot.middlewares.auth import AuthMiddleware


def test_create_bot_returns_bot_instance(fake_config: Config) -> None:
    bot = create_bot(fake_config)
    assert isinstance(bot, Bot)


def test_create_bot_uses_html_parse_mode(fake_config: Config) -> None:
    bot = create_bot(fake_config)
    assert bot.default.parse_mode == ParseMode.HTML  # type: ignore[union-attr]


# Dispatcher can only be created once per process because aiogram routers are
# module-level singletons — re-attaching them raises RuntimeError.
# Use a session-scoped fixture to create it exactly once.
@pytest.fixture(scope="session")
def dispatcher(fake_config: Config) -> Dispatcher:
    return create_dispatcher(fake_config)


@pytest.fixture(scope="session")
def fake_config() -> Config:  # type: ignore[override]
    return Config(
        telegram_bot_token="1234567890:AAFakeTokenForTestingPurposesOnly",
        anthropic_api_key="sk-ant-fake-key-for-testing",
        database_url="sqlite+aiosqlite:///:memory:",
        allowed_user_ids=[123456789],
    )


def test_create_dispatcher_returns_dispatcher(dispatcher: Dispatcher) -> None:
    assert isinstance(dispatcher, Dispatcher)


def test_create_dispatcher_includes_routers(dispatcher: Dispatcher) -> None:
    from bot.handlers import commands, messages, search, timezone_setup
    from bot.handlers import config as config_handler

    router_names = [r.name for r in dispatcher.sub_routers]
    assert commands.router.name in router_names
    assert config_handler.router.name in router_names
    assert messages.router.name in router_names
    assert search.router.name in router_names
    assert timezone_setup.router.name in router_names


def test_auth_middleware_registered_on_message(dispatcher: Dispatcher) -> None:
    assert any(isinstance(m, AuthMiddleware) for m in dispatcher.message.middleware)


def test_auth_middleware_registered_on_callback_query(dispatcher: Dispatcher) -> None:
    assert any(isinstance(m, AuthMiddleware) for m in dispatcher.callback_query.middleware)
