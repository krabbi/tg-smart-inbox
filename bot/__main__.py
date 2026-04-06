import asyncio
import logging

from aiogram.types import BotCommand

from bot.bot import create_bot, create_dispatcher
from bot.config import get_config
from bot.db import get_session_factory, init_db
from bot.middleware import DependencyMiddleware
from bot.scheduler import start_scheduler

_BOT_COMMANDS = [
    BotCommand(command="start", description="Начать работу"),
    BotCommand(command="list", description="Последние записи"),
    BotCommand(command="search", description="Поиск по записям"),
    BotCommand(command="reminders", description="Предстоящие напоминания"),
    BotCommand(command="ideas", description="Мои идеи"),
]


async def main() -> None:
    """Start the bot: initialise DB, start scheduler, and begin polling."""
    logging.basicConfig(level=logging.INFO)
    config = get_config()
    init_db(config.database_url)
    bot = create_bot(config)
    dp = create_dispatcher(config)
    factory = get_session_factory()
    dp.update.middleware(DependencyMiddleware(factory, config))
    start_scheduler(bot, factory)
    await bot.set_my_commands(_BOT_COMMANDS)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
