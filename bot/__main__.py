import asyncio
import logging

from bot.bot import create_bot, create_dispatcher
from bot.config import get_config
from bot.db import init_db


async def main() -> None:
    """Start the bot: initialise DB and begin polling."""
    logging.basicConfig(level=logging.INFO)
    config = get_config()
    init_db(config.database_url)
    bot = create_bot(config)
    dp = create_dispatcher(config)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
