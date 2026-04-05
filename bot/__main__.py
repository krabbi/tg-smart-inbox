import asyncio
import logging

from bot.bot import create_bot, create_dispatcher
from bot.config import get_config
from bot.db import get_session_factory, init_db
from bot.middleware import DependencyMiddleware


async def main() -> None:
    """Start the bot: initialise DB and begin polling."""
    logging.basicConfig(level=logging.INFO)
    config = get_config()
    init_db(config.database_url)
    bot = create_bot(config)
    dp = create_dispatcher(config)
    dp.update.middleware(DependencyMiddleware(get_session_factory(), config))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
