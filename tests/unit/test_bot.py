from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from bot.bot import create_bot, create_dispatcher
from bot.config import Config


def test_create_bot_returns_bot_instance(fake_config: Config) -> None:
    bot = create_bot(fake_config)
    assert isinstance(bot, Bot)


def test_create_bot_uses_html_parse_mode(fake_config: Config) -> None:
    bot = create_bot(fake_config)
    assert bot.default.parse_mode == ParseMode.HTML  # type: ignore[union-attr]


def test_create_dispatcher_returns_dispatcher() -> None:
    dp = create_dispatcher()
    assert isinstance(dp, Dispatcher)


def test_create_dispatcher_is_independent() -> None:
    dp1 = create_dispatcher()
    dp2 = create_dispatcher()
    assert dp1 is not dp2
