from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.note_service import NoteService


def make_item(content: str) -> Item:
    item = MagicMock(spec=Item)
    item.id = "some-uuid"
    item.content = content
    item.type = ItemType.note
    return item


def make_service(item: Item) -> NoteService:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    repo = MagicMock(spec=ItemRepository)
    repo.create = AsyncMock(return_value=item)
    return NoteService(session, repo)


async def test_save_creates_note_item() -> None:
    item = make_item("interesting fact")
    svc = make_service(item)

    result = await svc.save("interesting fact", user_id=1)

    svc._repo.create.assert_awaited_once_with(  # type: ignore[attr-defined]
        user_id=1, type=ItemType.note, content="interesting fact"
    )
    assert result.item is item


async def test_save_commits_session() -> None:
    svc = make_service(make_item("note"))
    await svc.save("note", user_id=1)
    svc._session.commit.assert_awaited_once()  # type: ignore[attr-defined]
