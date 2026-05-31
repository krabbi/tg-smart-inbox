import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.embedding_service import EmbeddingService
from bot.services.task_service import SavedTask, TaskService


def make_item(content: str) -> Item:
    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.content = content
    item.type = ItemType.task
    return item


def make_service(
    item: Item,
    *,
    embedding: list[float] | None = None,
    with_embedding_service: bool = False,
) -> tuple[TaskService, ItemRepository, AsyncSession]:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    repo = MagicMock(spec=ItemRepository)
    repo.create = AsyncMock(return_value=item)
    repo.update_embedding = AsyncMock()
    embedding_service: EmbeddingService | None = None
    if with_embedding_service:
        embedding_service = MagicMock(spec=EmbeddingService)
        embedding_service.generate_for_item = AsyncMock(return_value=embedding)
    return (
        TaskService(session, repo, embedding_service=embedding_service),
        repo,
        session,
    )


async def test_save_creates_task_item() -> None:
    item = make_item("buy milk")
    svc, repo, _ = make_service(item)

    result = await svc.save("buy milk", user_id=1)

    repo.create.assert_awaited_once_with(user_id=1, type=ItemType.task, content="buy milk")
    assert result.item is item


async def test_save_commits_session() -> None:
    svc, _, session = make_service(make_item("task"))
    await svc.save("task", user_id=1)
    session.commit.assert_awaited()


async def test_save_returns_saved_task() -> None:
    svc, _, _ = make_service(make_item("task"))
    saved = await svc.save("task", user_id=1)
    assert isinstance(saved, SavedTask)


async def test_save_without_embedding_service_returns_not_indexed() -> None:
    """When no EmbeddingService is wired, the task is still saved but not indexed."""
    svc, _, _ = make_service(make_item("task"))
    saved = await svc.save("task", user_id=1)
    assert saved.indexed is False


async def test_save_indexes_item_when_embedding_succeeds() -> None:
    svc, repo, _ = make_service(
        make_item("task"), with_embedding_service=True, embedding=[0.1] * 1024
    )
    saved = await svc.save("task", user_id=1)
    assert saved.indexed is True
    repo.update_embedding.assert_awaited_once()


async def test_save_marks_not_indexed_when_embedding_returns_none() -> None:
    svc, repo, _ = make_service(make_item("task"), with_embedding_service=True, embedding=None)
    saved = await svc.save("task", user_id=1)
    assert saved.indexed is False
    repo.update_embedding.assert_not_awaited()


async def test_save_marks_not_indexed_when_embedding_raises() -> None:
    svc, repo, _ = make_service(make_item("task"), with_embedding_service=True)
    # Override generate_for_item to raise.
    svc._embedding.generate_for_item = AsyncMock(  # type: ignore[union-attr]
        side_effect=Exception("Voyage API exploded")
    )
    saved = await svc.save("task", user_id=1)
    assert saved.indexed is False
    repo.update_embedding.assert_not_awaited()


async def test_save_rolls_back_when_embedding_persist_fails() -> None:
    svc, repo, session = make_service(
        make_item("task"), with_embedding_service=True, embedding=[0.2] * 1024
    )
    repo.update_embedding = AsyncMock(side_effect=Exception("DB error"))
    saved = await svc.save("task", user_id=1)
    assert saved.indexed is False
    session.rollback.assert_awaited()
