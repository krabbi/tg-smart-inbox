from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import Config
from bot.handlers import commands, links, messages
from bot.middlewares.auth import AuthMiddleware


def create_bot(config: Config) -> Bot:
    """Create a configured aiogram Bot instance."""
    return Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(config: Config) -> Dispatcher:
    """Create Dispatcher with all routers and middleware registered."""
    dp = Dispatcher()
    dp.message.middleware(AuthMiddleware(config))
    dp.include_router(commands.router)
    dp.include_router(links.router)
    dp.include_router(messages.router)
    return dp
