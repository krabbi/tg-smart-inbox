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

from bot.models.item import ItemType
from bot.services.list_service import _SEARCH_LIMIT, ListPage, ListService
from bot.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)

router = Router(name="commands")

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


def _list_keyboard(list_page: ListPage) -> InlineKeyboardMarkup | None:
    """Build prev/next pagination keyboard; return None if only one page."""
    if not list_page.has_prev and not list_page.has_next:
        return None
    buttons = []
    if list_page.has_prev:
        buttons.append(
            InlineKeyboardButton(text="← Назад", callback_data=f"list_page:{list_page.page - 1}")
        )
    if list_page.has_next:
        buttons.append(
            InlineKeyboardButton(text="Вперёд →", callback_data=f"list_page:{list_page.page + 1}")
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _format_list_page(list_page: ListPage) -> str:
    """Format a page of items as a text message."""
    lines = [f"📋 <b>Последние записи</b> (стр. {list_page.page + 1}):\n"]
    for item in list_page.items:
        emoji = _TYPE_EMOJI.get(item.type, "📄")
        snippet = item.content[:60] + ("…" if len(item.content) > 60 else "")
        date_str = item.created_at.strftime("%d.%m.%Y")
        lines.append(f"{emoji} {snippet}  <i>{date_str}</i>")
    lines.append(f"\n<i>Всего: {list_page.total}</i>")
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command with a welcome message."""
    await message.answer(WELCOME_TEXT)


@router.message(Command("list"))
async def cmd_list(
    message: Message,
    list_service: ListService | None = None,
) -> None:
    """Show the last 10 items for the user with pagination."""
    if list_service is None:
        logger.warning("list_service not injected — DI misconfiguration")
        await message.answer("Команда /list скоро будет доступна.")
        return

    user_id = message.from_user.id if message.from_user else 0
    list_page = await list_service.list_recent(user_id, page=0)

    if list_page.total == 0:
        await message.answer(
            "У тебя пока ничего не сохранено.\nПришли ссылку, задачу, идею или фото — я запомню!"
        )
        return

    reply = _format_list_page(list_page)
    kb = _list_keyboard(list_page)
    await message.answer(reply, reply_markup=kb)


@router.callback_query(F.data.startswith("list_page:"))
async def cb_list_page(
    callback: CallbackQuery,
    list_service: ListService | None = None,
) -> None:
    """Handle pagination for /list."""
    await callback.answer()
    if list_service is None or callback.message is None:
        return

    try:
        page = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    except (ValueError, IndexError):
        logger.warning("Invalid list_page callback data: %s", callback.data)
        return

    user_id = callback.from_user.id
    list_page = await list_service.list_recent(user_id, page=page)
    reply = _format_list_page(list_page)
    kb = _list_keyboard(list_page)
    try:
        await callback.message.edit_text(reply, reply_markup=kb)
    except Exception:
        logger.warning("Could not edit list message (already deleted or unchanged)")


@router.message(Command("search"))
async def cmd_search(
    message: Message,
    command: CommandObject,
    list_service: ListService | None = None,
) -> None:
    """Full-text search across saved items."""
    if list_service is None:
        logger.warning("list_service not injected — DI misconfiguration")
        await message.answer("Команда /search скоро будет доступна.")
        return

    query = (command.args or "").strip()
    if not query:
        await message.answer("Введи запрос: <code>/search чек из магазина</code>")
        return

    user_id = message.from_user.id if message.from_user else 0
    items = await list_service.search(user_id, query)

    if not items:
        await message.answer(f"Ничего не найдено по запросу: <b>{query}</b>")
        return

    lines = [f"🔍 <b>Результаты по «{query}»:</b>\n"]
    for item in items:
        emoji = _TYPE_EMOJI.get(item.type, "📄")
        snippet = item.content[:80] + ("…" if len(item.content) > 80 else "")
        date_str = item.created_at.strftime("%d.%m.%Y")
        lines.append(f"{emoji} {snippet}  <i>{date_str}</i>")

    if len(items) == _SEARCH_LIMIT:
        lines.append(f"\n<i>Показаны первые {_SEARCH_LIMIT} результатов</i>")

    await message.answer("\n".join(lines))


@router.message(Command("reminders"))
async def cmd_reminders(
    message: Message,
    reminder_service: ReminderService | None = None,
) -> None:
    """List upcoming reminders with cancel buttons."""
    if reminder_service is None:
        logger.warning("reminder_service not injected — DI misconfiguration")
        await message.answer("Команда /reminders скоро будет доступна.")
        return

    user_id = message.from_user.id if message.from_user else 0
    reminders = await reminder_service.get_upcoming(user_id)

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
    reminder_service: ReminderService | None = None,
) -> None:
    """Cancel a reminder — ownership is verified before cancelling."""
    if reminder_service is None or callback.message is None:
        await callback.answer()
        return

    try:
        reminder_id = uuid.UUID(callback.data.split(":")[1])  # type: ignore[union-attr]
    except (ValueError, IndexError):
        logger.warning("Invalid cancel_reminder callback data: %s", callback.data)
        await callback.answer("Неверный запрос.")
        return

    cancelled = await reminder_service.cancel_for_user(reminder_id, callback.from_user.id)
    if not cancelled:
        await callback.answer("Напоминание не найдено или уже отменено.")
        return

    await callback.answer()

    try:
        await callback.message.edit_text(
            callback.message.text + "\n\n<i>✅ Напоминание отменено</i>",  # type: ignore[operator]
            reply_markup=None,
        )
    except Exception:
        logger.warning("Could not edit reminder message after cancel")
