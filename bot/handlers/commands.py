from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router(name="commands")

WELCOME_TEXT = (
    "Привет! Я твой умный инбокс.\n\n"
    "Пересылай мне что угодно:\n"
    "• Ссылки — сохраню и сделаю саммари по запросу\n"
    "• Задачи — напомню в нужное время\n"
    "• Фото и файлы — сохраню в Google Drive\n"
    "• Идеи — накоплю и помогу выбрать что делать\n\n"
    "Просто пришли мне сообщение!"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command with a welcome message."""
    await message.answer(WELCOME_TEXT)
