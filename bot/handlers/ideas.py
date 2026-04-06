import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.services.idea_service import IdeaService

logger = logging.getLogger(__name__)

router = Router(name="ideas")

_IDEAS_PER_PAGE = 10


@router.message(Command("ideas"))
async def handle_ideas_command(
    message: Message,
    idea_service: IdeaService | None = None,
) -> None:
    """Show the user's saved ideas list, up to 10 most recent."""
    if idea_service is None:
        logger.warning("idea_service not injected — DI misconfiguration")
        await message.answer("Команда /ideas скоро будет доступна.")
        return

    user_id = message.from_user.id if message.from_user else 0
    rows = await idea_service.get_all(user_id)

    if not rows:
        await message.answer("У тебя пока нет идей. Поделись — просто напиши идею!")
        return

    lines = ["💡 <b>Твои идеи:</b>\n"]
    for i, (item, idea) in enumerate(rows[:_IDEAS_PER_PAGE], 1):
        snippet = item.content[:80] + ("…" if len(item.content) > 80 else "")
        tags_str = " ".join(f"#{t}" for t in idea.tags) if idea.tags else ""
        date_str = item.created_at.strftime("%d.%m.%Y")
        entry = f"{i}. {snippet}"
        if tags_str:
            entry += f"\n   {tags_str}"
        entry += f"  <i>{date_str}</i>"
        lines.append(entry)

    if len(rows) > _IDEAS_PER_PAGE:
        lines.append(f"\n<i>Показаны {_IDEAS_PER_PAGE} из {len(rows)}</i>")

    await message.answer("\n\n".join(lines))
