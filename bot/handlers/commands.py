import logging
import uuid

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import Config
from bot.handlers.timezone_setup import start_timezone_setup
from bot.models.item import ItemType
from bot.services.list_service import ListPage, ListService
from bot.services.reminder_service import ReminderService
from bot.services.user_settings_service import UserSettingsService
from bot.utils.datetime_utils import format_remind_at

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
    "Просто пришли мне сообщение — я автоматически определю тип и сохраню:\n"
    "• <b>Ссылку</b> — сохраню и предложу саммари\n"
    "• <b>Задачу</b> — сохраню и предложу напоминание\n"
    "• <b>Идею</b> — сохраню с тегами и оценкой сложности\n"
    "• <b>Заметку</b> — просто сохраню на память\n\n"
    "<b>Команды:</b>\n"
    "/list — последние записи\n"
    "/search — поиск по сохранённому\n"
    "/reminders — предстоящие напоминания\n"
    "/ideas — банк идей\n"
    "/config — настройки (например, часовой пояс)\n"
    "/help — подробная справка\n"
    "/cancel — отмена текущего действия"
)

_HELP_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Подробнее", callback_data="help")]]
)


def _build_help_text(config: Config) -> str:
    """Build the detailed help message, hiding unconfigured optional features."""
    sections = [
        "<b>Подробная справка</b>\n",
        (
            "<b>Типы контента</b>\n"
            "Отправь любое сообщение — бот определит тип автоматически:\n\n"
            "🔗 <b>Ссылка</b> — отправь URL, например:\n"
            "<code>https://example.com/interesting-article</code>\n"
            "Бот сохранит и предложит кнопки: Саммари, Сохранить, Напомнить.\n\n"
            "✅ <b>Задача</b> — напиши что нужно сделать, например:\n"
            "<code>купить молоко завтра</code>\n"
            "Бот предложит создать напоминание на нужное время.\n\n"
            "💡 <b>Идея</b> — напиши идею или концепцию, например:\n"
            "<code>а что если сделать бота для учёта расходов</code>\n"
            "Бот сохранит с тегами и оценкой сложности.\n"
            "Напиши <code>что поделать?</code> — бот предложит идею из банка.\n\n"
            "📝 <b>Заметка</b> — любой другой текст сохранится как заметка."
        ),
    ]

    if config.groq_api_key:
        sections.append(
            "🎤 <b>Голосовые сообщения</b>\n"
            "Отправь голосовое — бот расшифрует и обработает как текст."
        )

    if config.google_drive_folder_id:
        sections.append(
            "🖼️ <b>Фото и файлы</b>\nОтправь фото или документ — бот загрузит в Google Drive."
        )

    sections.append(
        "<b>Напоминания</b>\n"
        "Когда напоминание сработает, появятся кнопки:\n"
        "⏰ +1ч — отложить на час\n"
        "🌙 +1д — отложить на день\n"
        "✅ Принято — отметить выполненным\n"
        "Если не нажать кнопку — бот напомнит повторно через 5 минут."
    )

    sections.append(
        "<b>Команды</b>\n"
        "/list — последние 10 записей с пагинацией\n"
        "/search — поиск по сохранённому (обычный или умный AI)\n"
        "/reminders — список предстоящих напоминаний\n"
        "/ideas — банк идей с тегами и сложностью\n"
        "/config — настройки (часовой пояс и т.д.)\n"
        "/help — эта справка\n"
        "/cancel — отмена текущего действия"
    )

    return "\n\n".join(sections)


_TYPE_FILTER_LABEL = {
    None: "Все",
    ItemType.link: "🔗 Ссылки",
    ItemType.task: "✅ Задачи",
    ItemType.idea: "💡 Идеи",
    ItemType.note: "📝 Заметки",
}

_TYPE_FILTER_ORDER: list[ItemType | None] = [
    None,
    ItemType.link,
    ItemType.task,
    ItemType.idea,
    ItemType.note,
]


def _type_suffix(item_type: ItemType | None) -> str:
    """Return callback data suffix for the current type filter."""
    return item_type.value if item_type else "all"


def _list_keyboard(list_page: ListPage) -> InlineKeyboardMarkup:
    """Build filter + prev/next pagination keyboard."""
    # Filter row
    filter_buttons = []
    for ft in _TYPE_FILTER_ORDER:
        label = _TYPE_FILTER_LABEL[ft]
        if ft == list_page.item_type:
            label = f"[{label}]"
        cb_data = f"list_filter:{_type_suffix(ft)}"
        filter_buttons.append(InlineKeyboardButton(text=label, callback_data=cb_data))

    rows: list[list[InlineKeyboardButton]] = [filter_buttons]

    # Pagination row
    nav_buttons = []
    if list_page.has_prev:
        suffix = _type_suffix(list_page.item_type)
        nav_buttons.append(
            InlineKeyboardButton(
                text="← Назад", callback_data=f"list_page:{list_page.page - 1}:{suffix}"
            )
        )
    if list_page.has_next:
        suffix = _type_suffix(list_page.item_type)
        nav_buttons.append(
            InlineKeyboardButton(
                text="Вперёд →", callback_data=f"list_page:{list_page.page + 1}:{suffix}"
            )
        )
    if nav_buttons:
        rows.append(nav_buttons)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _parse_type_suffix(suffix: str) -> ItemType | None:
    """Parse type filter suffix back to ItemType or None."""
    if suffix == "all":
        return None
    try:
        return ItemType(suffix)
    except ValueError:
        return None


def _format_list_page(list_page: ListPage) -> str:
    """Format a page of items as a text message."""
    if list_page.item_type is not None:
        type_label = _TYPE_FILTER_LABEL.get(list_page.item_type, "")
        header = f"📋 <b>{type_label}</b> (стр. {list_page.page + 1}):\n"
    else:
        header = f"📋 <b>Последние записи</b> (стр. {list_page.page + 1}):\n"
    lines = [header]
    for item in list_page.items:
        emoji = _TYPE_EMOJI.get(item.type, "📄")
        snippet = item.content[:60] + ("…" if len(item.content) > 60 else "")
        date_str = item.created_at.strftime("%d.%m.%Y")
        lines.append(f"{emoji} {snippet}  <i>{date_str}</i>")
    lines.append(f"\n<i>Всего: {list_page.total}</i>")
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user_settings_service: UserSettingsService | None = None,
) -> None:
    """Handle /start — run timezone setup on first run, else show the welcome message."""
    user_id = message.from_user.id if message.from_user else 0

    # First-run path: no stored settings row → no user-confirmed timezone yet.
    # `get_timezone()` returns the default ("UTC") both when the row is missing and when
    # the user explicitly picked UTC, so we query the repo directly via the service's
    # underlying repository only if the service is actually wired — otherwise fall back
    # to the welcome message so the bot still replies when DI is misconfigured.
    if user_settings_service is not None and user_id:
        has_tz = await user_settings_service.has_timezone(user_id)
        if not has_tz:
            await start_timezone_setup(message, state)
            return

    await message.answer(WELCOME_TEXT, reply_markup=_HELP_KEYBOARD)


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config | None = None) -> None:
    """Show detailed help message with all features and examples."""
    if config is None:
        await message.answer(WELCOME_TEXT, reply_markup=_HELP_KEYBOARD)
        return
    await message.answer(_build_help_text(config))


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery, config: Config | None = None) -> None:
    """Show detailed help when the inline button is pressed."""
    await callback.answer()
    if callback.message is None:
        return
    if config is None:
        await callback.message.answer(WELCOME_TEXT)
        return
    await callback.message.answer(_build_help_text(config))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Cancel any active FSM dialog (e.g. reminder time input)."""
    current = await state.get_state()
    if current is None:
        await message.answer("Нет активного действия для отмены.")
        return
    await state.clear()
    await message.answer("Отменено.")


@router.message(Command("list"))
async def cmd_list(
    message: Message,
    list_service: ListService | None = None,
) -> None:
    """Show the last 10 items for the user with pagination and type filter."""
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

    parts = callback.data.split(":")  # type: ignore[union-attr]
    try:
        page = int(parts[1])
    except (ValueError, IndexError):
        logger.warning("Invalid list_page callback data: %s", callback.data)
        return

    item_type = _parse_type_suffix(parts[2]) if len(parts) > 2 else None

    user_id = callback.from_user.id
    list_page = await list_service.list_recent(user_id, page=page, item_type=item_type)
    reply = _format_list_page(list_page)
    kb = _list_keyboard(list_page)
    try:
        await callback.message.edit_text(reply, reply_markup=kb)
    except Exception:
        logger.warning("Could not edit list message (already deleted or unchanged)")


@router.callback_query(F.data.startswith("list_filter:"))
async def cb_list_filter(
    callback: CallbackQuery,
    list_service: ListService | None = None,
) -> None:
    """Handle type filter selection for /list."""
    await callback.answer()
    if list_service is None or callback.message is None:
        return

    suffix = callback.data.split(":")[1]  # type: ignore[union-attr]
    item_type = _parse_type_suffix(suffix)

    user_id = callback.from_user.id
    list_page = await list_service.list_recent(user_id, page=0, item_type=item_type)
    reply = _format_list_page(list_page)
    kb = _list_keyboard(list_page)
    try:
        await callback.message.edit_text(reply, reply_markup=kb)
    except Exception:
        logger.warning("Could not edit list message (already deleted or unchanged)")


@router.message(Command("reminders"))
async def cmd_reminders(
    message: Message,
    reminder_service: ReminderService | None = None,
    user_settings_service: UserSettingsService | None = None,
) -> None:
    """List upcoming reminders with cancel buttons."""
    if reminder_service is None:
        logger.warning("reminder_service not injected — DI misconfiguration")
        await message.answer("Команда /reminders скоро будет доступна.")
        return

    user_id = message.from_user.id if message.from_user else 0
    reminders = await reminder_service.get_upcoming(user_id)

    if not reminders:
        await message.answer(
            "У тебя нет предстоящих напоминаний. "
            "Отправь задачу и выбери время, чтобы создать напоминание."
        )
        return

    user_tz = "UTC"
    if user_settings_service is not None and user_id:
        user_tz = await user_settings_service.get_timezone(user_id)

    for reminder in reminders:
        item = reminder.item
        due = format_remind_at(reminder.remind_at, user_tz)
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
