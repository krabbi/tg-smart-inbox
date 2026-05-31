import asyncio
import logging

from aiogram.types import BotCommand

from bot.bot import create_bot, create_dispatcher
from bot.config import get_config
from bot.db import get_session_factory, init_db
from bot.i18n import t
from bot.middleware import DependencyMiddleware
from bot.scheduler import start_scheduler


def _bot_commands_for(lang: str) -> list[BotCommand]:
    """Build the Telegram commands menu localized to ``lang``."""
    return [
        BotCommand(command="start", description=t("botcmd_start", lang)),
        BotCommand(command="list", description=t("botcmd_list", lang)),
        BotCommand(command="search", description=t("botcmd_search", lang)),
        BotCommand(command="reminders", description=t("botcmd_reminders", lang)),
        BotCommand(command="ideas", description=t("botcmd_ideas", lang)),
        BotCommand(command="config", description=t("botcmd_config", lang)),
        BotCommand(command="reindex", description=t("commands.reindex.description", lang)),
        BotCommand(command="cancel", description=t("botcmd_cancel", lang)),
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
    start_scheduler(bot, factory, config)
    # Telegram supports per-language command descriptions; we register both.
    await bot.set_my_commands(_bot_commands_for("ru"), language_code="ru")
    await bot.set_my_commands(_bot_commands_for("en"))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
