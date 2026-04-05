import asyncio
import logging

from bot.bot import create_bot, create_dispatcher
from bot.config import get_config


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = get_config()
    bot = create_bot(config)
    dp = create_dispatcher()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
