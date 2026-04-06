from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.task_service import TaskService


def make_item(content: str) -> Item:
    item = MagicMock(spec=Item)
    item.id = "some-uuid"
    item.content = content
    item.type = ItemType.task
    return item


def make_service(item: Item) -> TaskService:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    repo = MagicMock(spec=ItemRepository)
    repo.create = AsyncMock(return_value=item)
    return TaskService(session, repo)


async def test_save_creates_task_item() -> None:
    item = make_item("buy milk")
    svc = make_service(item)

    result = await svc.save("buy milk", user_id=1)

    svc._repo.create.assert_awaited_once_with(  # type: ignore[attr-defined]
        user_id=1, type=ItemType.task, content="buy milk"
    )
    assert result.item is item


async def test_save_commits_session() -> None:
    svc = make_service(make_item("task"))
    await svc.save("task", user_id=1)
    svc._session.commit.assert_awaited_once()  # type: ignore[attr-defined]
