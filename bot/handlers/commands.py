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
from bot.i18n import t
from bot.models.item import ItemType
from bot.services.embedding_service import EmbeddingService
from bot.services.list_service import ListPage, ListService
from bot.services.reindex_service import ReindexService
from bot.services.reminder_service import ReminderService
from bot.services.user_settings_service import UserSettingsService
from bot.utils.datetime_utils import format_remind_at
from bot.utils.text import format_item_display

logger = logging.getLogger(__name__)

router = Router(name="commands")

_TYPE_EMOJI = {
    ItemType.link: "🔗",
    ItemType.note: "📝",
    ItemType.task: "✅",
    ItemType.media: "🖼️",
    ItemType.idea: "💡",
}


def _help_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the inline 'More' button shown under the welcome message."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("help_button_more", lang), callback_data="help")]
        ]
    )


def _build_help_text(config: Config, lang: str) -> str:
    """Build the detailed help message, hiding unconfigured optional features."""
    sections = [t("help_title", lang), t("help_content_types", lang)]

    if config.groq_api_key:
        sections.append(t("help_voice", lang))

    if config.google_drive_folder_id:
        sections.append(t("help_media", lang))

    sections.append(t("help_reminders", lang))
    sections.append(t("help_commands", lang))

    return "\n\n".join(sections)


_TYPE_FILTER_LABEL_KEY = {
    None: "list_filter_all",
    ItemType.link: "list_filter_links",
    ItemType.task: "list_filter_tasks",
    ItemType.idea: "list_filter_ideas",
    ItemType.note: "list_filter_notes",
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


def _list_keyboard(list_page: ListPage, lang: str) -> InlineKeyboardMarkup:
    """Build filter + prev/next pagination keyboard."""
    # Filter row
    filter_buttons = []
    for ft in _TYPE_FILTER_ORDER:
        label = t(_TYPE_FILTER_LABEL_KEY[ft], lang)
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
                text=t("pagination_prev", lang),
                callback_data=f"list_page:{list_page.page - 1}:{suffix}",
            )
        )
    if list_page.has_next:
        suffix = _type_suffix(list_page.item_type)
        nav_buttons.append(
            InlineKeyboardButton(
                text=t("pagination_next", lang),
                callback_data=f"list_page:{list_page.page + 1}:{suffix}",
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


def _format_list_page(list_page: ListPage, lang: str) -> str:
    """Format a page of items as a text message."""
    if list_page.item_type is not None:
        type_label = t(_TYPE_FILTER_LABEL_KEY[list_page.item_type], lang)
        header = t("list_header_filtered", lang, label=type_label, page=list_page.page + 1)
    else:
        header = t("list_header_all", lang, page=list_page.page + 1)
    lines = [header]
    for item in list_page.items:
        emoji = _TYPE_EMOJI.get(item.type, "📄")
        display = format_item_display(item)
        snippet = display[:60] + ("…" if len(display) > 60 else "")
        date_str = item.created_at.strftime("%d.%m.%Y")
        lines.append(f"{emoji} {snippet}  <i>{date_str}</i>")
    lines.append(t("list_total", lang, total=list_page.total))
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user_settings_service: UserSettingsService | None = None,
    lang: str = "en",
) -> None:
    """Handle /start — run timezone setup on first run, else show the welcome message."""
    user_id = message.from_user.id if message.from_user else 0
    language_code = message.from_user.language_code if message.from_user else None

    if user_settings_service is not None and user_id:
        has_tz = await user_settings_service.has_timezone(user_id)
        if not has_tz:
            # Brand-new user: no settings row yet, so no timezone has been confirmed.
            # Launch the three-step timezone picker.  The settings row is created by
            # `set_timezone` once the user completes the FSM — we intentionally do NOT
            # call `ensure_user_settings` here so that `has_timezone` continues to
            # distinguish "never configured" from "explicitly chose UTC".
            await start_timezone_setup(message, state, lang)
            return

        # Settings row already exists (timezone was previously set).
        # Ensure the row is present — this is a no-op for returning users and
        # creates it with sensible defaults for users who reach the welcome screen
        # on a path other than the timezone FSM (e.g. the row was deleted and
        # the user typed /start again after their timezone was externally cleared).
        await user_settings_service.ensure_user_settings(user_id, language_code)

    await message.answer(t("welcome", lang), reply_markup=_help_keyboard(lang))


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config | None = None, lang: str = "en") -> None:
    """Show detailed help message with all features and examples."""
    if config is None:
        await message.answer(t("welcome", lang), reply_markup=_help_keyboard(lang))
        return
    await message.answer(_build_help_text(config, lang))


@router.callback_query(F.data == "help")
async def cb_help(
    callback: CallbackQuery,
    config: Config | None = None,
    lang: str = "en",
) -> None:
    """Show detailed help when the inline button is pressed."""
    await callback.answer()
    if callback.message is None:
        return
    if config is None:
        await callback.message.answer(t("welcome", lang))
        return
    await callback.message.answer(_build_help_text(config, lang))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, lang: str = "en") -> None:
    """Cancel any active FSM dialog (e.g. reminder time input)."""
    current = await state.get_state()
    if current is None:
        await message.answer(t("cancel_nothing_to_cancel", lang))
        return
    await state.clear()
    await message.answer(t("cancel_done", lang))


@router.message(Command("list"))
async def cmd_list(
    message: Message,
    list_service: ListService | None = None,
    lang: str = "en",
) -> None:
    """Show the last 10 items for the user with pagination and type filter."""
    if list_service is None:
        logger.warning("list_service not injected — DI misconfiguration")
        await message.answer(t("list_command_unavailable", lang))
        return

    user_id = message.from_user.id if message.from_user else 0
    list_page = await list_service.list_recent(user_id, page=0)

    if list_page.total == 0:
        await message.answer(t("list_empty", lang))
        return

    reply = _format_list_page(list_page, lang)
    kb = _list_keyboard(list_page, lang)
    await message.answer(reply, reply_markup=kb)


@router.callback_query(F.data.startswith("list_page:"))
async def cb_list_page(
    callback: CallbackQuery,
    list_service: ListService | None = None,
    lang: str = "en",
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
    reply = _format_list_page(list_page, lang)
    kb = _list_keyboard(list_page, lang)
    try:
        await callback.message.edit_text(reply, reply_markup=kb)
    except Exception:
        logger.warning("Could not edit list message (already deleted or unchanged)")


@router.callback_query(F.data.startswith("list_filter:"))
async def cb_list_filter(
    callback: CallbackQuery,
    list_service: ListService | None = None,
    lang: str = "en",
) -> None:
    """Handle type filter selection for /list."""
    await callback.answer()
    if list_service is None or callback.message is None:
        return

    suffix = callback.data.split(":")[1]  # type: ignore[union-attr]
    item_type = _parse_type_suffix(suffix)

    user_id = callback.from_user.id
    list_page = await list_service.list_recent(user_id, page=0, item_type=item_type)
    reply = _format_list_page(list_page, lang)
    kb = _list_keyboard(list_page, lang)
    try:
        await callback.message.edit_text(reply, reply_markup=kb)
    except Exception:
        logger.warning("Could not edit list message (already deleted or unchanged)")


@router.message(Command("reminders"))
async def cmd_reminders(
    message: Message,
    reminder_service: ReminderService | None = None,
    user_settings_service: UserSettingsService | None = None,
    lang: str = "en",
) -> None:
    """List upcoming reminders with cancel buttons."""
    if reminder_service is None:
        logger.warning("reminder_service not injected — DI misconfiguration")
        await message.answer(t("reminders_command_unavailable", lang))
        return

    user_id = message.from_user.id if message.from_user else 0
    reminders = await reminder_service.get_upcoming(user_id)

    if not reminders:
        await message.answer(t("reminders_empty", lang))
        return

    user_tz = "UTC"
    if user_settings_service is not None and user_id:
        user_tz = await user_settings_service.get_timezone(user_id)

    for reminder in reminders:
        item = reminder.item
        due = format_remind_at(reminder.remind_at, user_tz)
        display = format_item_display(item)
        text = t("reminders_entry", lang, content=display[:100], due=due)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("reminder_btn_cancel", lang),
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
    lang: str = "en",
) -> None:
    """Cancel a reminder — ownership is verified before cancelling."""
    if reminder_service is None or callback.message is None:
        await callback.answer()
        return

    try:
        reminder_id = uuid.UUID(callback.data.split(":")[1])  # type: ignore[union-attr]
    except (ValueError, IndexError):
        logger.warning("Invalid cancel_reminder callback data: %s", callback.data)
        await callback.answer(t("reminder_cancel_invalid", lang))
        return

    cancelled = await reminder_service.cancel_for_user(reminder_id, callback.from_user.id)
    if not cancelled:
        await callback.answer(t("reminder_cancel_not_found", lang))
        return

    await callback.answer()

    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n<i>{t('reminder_cancelled_marker', lang)}</i>",  # type: ignore[operator]
            reply_markup=None,
        )
    except Exception:
        logger.warning("Could not edit reminder message after cancel")


# ── /reindex ──────────────────────────────────────────────────────────────────

# Bulk reindex cap — mirrors ``ReindexService`` default. Surfaced here so the
# pre-run "(first 200 will be processed)" suffix and the run itself stay in sync.
_REINDEX_MAX_ITEMS = 200


@router.message(Command("reindex"))
async def cmd_reindex(
    message: Message,
    reindex_service: ReindexService | None = None,
    embedding_service: EmbeddingService | None = None,
    lang: str = "en",
) -> None:
    """Reindex up to 200 of the user's records that currently have no embedding."""
    if reindex_service is None or embedding_service is None:
        logger.warning("reindex_service or embedding_service not injected — DI misconfiguration")
        await message.answer(t("reindex.all.not_configured", lang))
        return

    if not embedding_service.is_configured:
        await message.answer(t("reindex.all.not_configured", lang))
        return

    user_id = message.from_user.id if message.from_user else 0
    if not user_id:
        return

    if not ReindexService.try_start_user_reindex(user_id):
        await message.answer(t("reindex.all.already_running", lang))
        return

    try:
        total = await reindex_service.count_unindexed_for_user(user_id)
        if total == 0:
            await message.answer(t("reindex.all.already_indexed", lang))
            return

        in_progress_text = t("reindex.all.in_progress", lang, count=total)
        if total > _REINDEX_MAX_ITEMS:
            in_progress_text += t("reindex.all.in_progress_truncated_suffix", lang)
        await message.answer(in_progress_text)

        summary = await reindex_service.reindex_all_for_user(user_id, max_items=_REINDEX_MAX_ITEMS)
    finally:
        ReindexService.finish_user_reindex(user_id)

    if summary.succeeded == 0 and summary.failed > 0:
        await message.answer(t("reindex.all.unavailable", lang))
        return

    result_text = t("reindex.all.done", lang, succeeded=summary.succeeded)
    if summary.failed > 0:
        result_text += t("reindex.all.done_with_failures_suffix", lang, failed=summary.failed)
    if summary.truncated:
        result_text += "\n" + t("reindex.all.done_truncated_suffix", lang)
    await message.answer(result_text)
