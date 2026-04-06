from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Message

from bot.handlers.ideas import handle_ideas_command
from bot.models.idea import Idea, IdeaComplexity, IdeaEffort
from bot.models.item import Item
from bot.services.idea_service import IdeaService


def make_message(user_id: int = 1) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    return msg


def make_idea_row(
    content: str,
    tags: list[str],
    complexity: IdeaComplexity | None = None,
    effort: IdeaEffort | None = None,
) -> tuple[MagicMock, MagicMock]:
    item = MagicMock(spec=Item)
    item.content = content
    item.created_at = MagicMock()
    item.created_at.strftime = MagicMock(return_value="01.01.2026")
    idea = MagicMock(spec=Idea)
    idea.tags = tags
    idea.complexity = complexity
    idea.effort = effort
    return item, idea


async def test_handle_ideas_no_service_sends_stub() -> None:
    msg = make_message()
    await handle_ideas_command(msg, idea_service=None)
    msg.answer.assert_awaited_once()
    assert "скоро" in msg.answer.call_args[0][0]


async def test_handle_ideas_empty_list() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    svc.get_all = AsyncMock(return_value=[])

    await handle_ideas_command(msg, idea_service=svc)
    msg.answer.assert_awaited_once()
    assert (
        "нет идей" in msg.answer.call_args[0][0].lower()
        or "пока" in msg.answer.call_args[0][0].lower()
    )


async def test_handle_ideas_shows_list() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    svc.get_all = AsyncMock(
        return_value=[
            make_idea_row("Build a Telegram bot", ["bot", "telegram"]),
            make_idea_row("Write a novel", ["writing"]),
        ]
    )

    await handle_ideas_command(msg, idea_service=svc)
    reply = msg.answer.call_args[0][0]
    assert "Telegram bot" in reply
    assert "#bot" in reply
    assert "novel" in reply


async def test_handle_ideas_truncates_long_content() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    long_text = "a" * 200
    svc.get_all = AsyncMock(return_value=[make_idea_row(long_text, [])])

    await handle_ideas_command(msg, idea_service=svc)
    reply = msg.answer.call_args[0][0]
    assert "…" in reply


async def test_handle_ideas_shows_complexity_and_effort() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    svc.get_all = AsyncMock(
        return_value=[
            make_idea_row(
                "Build a helicopter",
                [],
                complexity=IdeaComplexity.complex,
                effort=IdeaEffort.longterm,
            )
        ]
    )

    await handle_ideas_command(msg, idea_service=svc)
    reply = msg.answer.call_args[0][0]
    assert "сложная" in reply
    assert "долгосрочно" in reply


async def test_handle_ideas_shows_count_when_many() -> None:
    msg = make_message()
    svc = MagicMock(spec=IdeaService)
    rows = [make_idea_row(f"idea {i}", []) for i in range(15)]
    svc.get_all = AsyncMock(return_value=rows)

    await handle_ideas_command(msg, idea_service=svc)
    reply = msg.answer.call_args[0][0]
    assert "15" in reply
