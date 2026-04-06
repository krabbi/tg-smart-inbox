import logging
import uuid

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import ItemType
from bot.repositories.item_repository import ItemRepository
from bot.repositories.reminder_repository import ReminderRepository

logger = logging.getLogger(__name__)

router = Router(name="commands")

_PAGE_SIZE = 10

_TYPE_EMOJI = {
    ItemType.link: "🔗",
    ItemType.note: "📝",
    ItemType.task: "✅",
    ItemType.media: "🖼️",
    ItemType.idea: "💡",
}

WELCOME_TEXT = (
    "Привет! Я твой умный инбокс.\n\n"
    "Пересылай мне что угодно:\n"
    "• Ссылки — сохраню и сделаю саммари по запросу\n"
    "• Задачи — напомню в нужное время\n"
    "• Фото и файлы — сохраню в Google Drive\n"
    "• Идеи — накоплю и помогу выбрать что делать\n\n"
    "Просто пришли мне сообщение!"
)


def _list_keyboard(page: int, total: int) -> InlineKeyboardMarkup | None:
    """Build prev/next pagination keyboard; return None if single page."""
    has_prev = page > 0
    has_next = (page + 1) * _PAGE_SIZE < total
    if not has_prev and not has_next:
        return None
    buttons = []
    if has_prev:
        buttons.append(InlineKeyboardButton(text="← Назад", callback_data=f"list_page:{page - 1}"))
    if has_next:
        buttons.append(InlineKeyboardButton(text="Вперёд →", callback_data=f"list_page:{page + 1}"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _format_list_page(items: list, page: int, total: int) -> str:
    """Format a page of items as a text message."""
    lines = [f"📋 <b>Последние записи</b> (стр. {page + 1}):\n"]
    for item in items:
        emoji = _TYPE_EMOJI.get(item.type, "📄")
        snippet = item.content[:60] + ("…" if len(item.content) > 60 else "")
        date_str = item.created_at.strftime("%d.%m.%Y")
        lines.append(f"{emoji} {snippet}  <i>{date_str}</i>")
    lines.append(f"\n<i>Всего: {total}</i>")
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command with a welcome message."""
    await message.answer(WELCOME_TEXT)


@router.message(Command("list"))
async def cmd_list(
    message: Message,
    item_repo: ItemRepository | None = None,
) -> None:
    """Show the last 10 items for the user with pagination."""
    if item_repo is None:
        logger.warning("item_repo not injected — DI misconfiguration")
        await message.answer("Команда /list скоро будет доступна.")
        return

    user_id = message.from_user.id if message.from_user else 0
    total = await item_repo.count_by_user(user_id)

    if total == 0:
        await message.answer(
            "У тебя пока ничего не сохранено.\nПришли ссылку, задачу, идею или фото — я запомню!"
        )
        return

    items = await item_repo.get_recent(user_id, limit=_PAGE_SIZE, offset=0)
    reply = _format_list_page(items, page=0, total=total)
    kb = _list_keyboard(page=0, total=total)
    await message.answer(reply, reply_markup=kb)


@router.callback_query(F.data.startswith("list_page:"))
async def cb_list_page(
    callback: CallbackQuery,
    item_repo: ItemRepository | None = None,
) -> None:
    """Handle pagination for /list."""
    await callback.answer()
    if item_repo is None or callback.message is None:
        return

    page = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    user_id = callback.from_user.id
    total = await item_repo.count_by_user(user_id)
    items = await item_repo.get_recent(user_id, limit=_PAGE_SIZE, offset=page * _PAGE_SIZE)

    reply = _format_list_page(items, page=page, total=total)
    kb = _list_keyboard(page=page, total=total)
    await callback.message.edit_text(reply, reply_markup=kb)


@router.message(Command("search"))
async def cmd_search(
    message: Message,
    command: CommandObject,
    item_repo: ItemRepository | None = None,
) -> None:
    """Full-text search across saved items."""
    if item_repo is None:
        logger.warning("item_repo not injected — DI misconfiguration")
        await message.answer("Команда /search скоро будет доступна.")
        return

    query = (command.args or "").strip()
    if not query:
        await message.answer("Введи запрос: <code>/search чек из магазина</code>")
        return

    user_id = message.from_user.id if message.from_user else 0
    items = await item_repo.search(user_id, query)

    if not items:
        await message.answer(f"Ничего не найдено по запросу: <b>{query}</b>")
        return

    lines = [f"🔍 <b>Результаты по «{query}»:</b>\n"]
    for item in items:
        emoji = _TYPE_EMOJI.get(item.type, "📄")
        snippet = item.content[:80] + ("…" if len(item.content) > 80 else "")
        date_str = item.created_at.strftime("%d.%m.%Y")
        lines.append(f"{emoji} {snippet}  <i>{date_str}</i>")

    await message.answer("\n".join(lines))


@router.message(Command("reminders"))
async def cmd_reminders(
    message: Message,
    reminder_repo: ReminderRepository | None = None,
) -> None:
    """List upcoming reminders with cancel buttons."""
    if reminder_repo is None:
        logger.warning("reminder_repo not injected — DI misconfiguration")
        await message.answer("Команда /reminders скоро будет доступна.")
        return

    user_id = message.from_user.id if message.from_user else 0
    reminders = await reminder_repo.get_upcoming(user_id)

    if not reminders:
        await message.answer("У тебя нет предстоящих напоминаний.")
        return

    for reminder in reminders:
        item = reminder.item
        due = reminder.remind_at.strftime("%d.%m.%Y %H:%M")
        text = f"⏰ <b>{item.content[:100]}</b>\n🗓 {due}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Отменить",
                        callback_data=f"cancel_reminder:{reminder.id}",
                    )
                ]
            ]
        )
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("cancel_reminder:"))
async def cb_cancel_reminder(
    callback: CallbackQuery,
    reminder_repo: ReminderRepository | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Cancel a specific reminder and update the message."""
    await callback.answer()
    if reminder_repo is None or session is None or callback.message is None:
        return

    reminder_id = uuid.UUID(callback.data.split(":")[1])  # type: ignore[union-attr]
    await reminder_repo.cancel(reminder_id)
    await session.commit()
    await callback.message.edit_text(
        callback.message.text + "\n\n<i>✅ Напоминание отменено</i>",  # type: ignore[operator]
        reply_markup=None,
    )
