"""Tests for ItemRepository.get_recent, count_by_user, and search."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository


async def _create_item(
    repo: ItemRepository,
    session: AsyncSession,
    content: str,
    user_id: int = 1,
    item_type: ItemType = ItemType.note,
    description: str | None = None,
) -> Item:
    item = await repo.create(user_id=user_id, type=item_type, content=content)
    if description is not None:
        item.description = description
    await session.commit()
    return item


async def test_get_recent_returns_items(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await _create_item(repo, db_session, "first")
    await _create_item(repo, db_session, "second")

    items = await repo.get_recent(user_id=1)
    assert len(items) == 2


async def test_get_recent_respects_limit(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    for i in range(15):
        await _create_item(repo, db_session, f"item {i}")

    items = await repo.get_recent(user_id=1, limit=5)
    assert len(items) == 5


async def test_get_recent_offset_paginates(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    for i in range(12):
        item = await repo.create(user_id=1, type=ItemType.note, content=f"item {i}")
        # Back-date earlier items so ordering is deterministic
        await db_session.execute(
            update(Item)
            .where(Item.id == item.id)
            .values(created_at=datetime.now(tz=UTC) - timedelta(seconds=12 - i))
        )
        await db_session.commit()

    page1 = await repo.get_recent(user_id=1, limit=10, offset=0)
    page2 = await repo.get_recent(user_id=1, limit=10, offset=10)
    assert len(page1) == 10
    assert len(page2) == 2
    # No overlap
    ids1 = {i.id for i in page1}
    ids2 = {i.id for i in page2}
    assert ids1.isdisjoint(ids2)


async def test_count_by_user(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    assert await repo.count_by_user(user_id=1) == 0
    await _create_item(repo, db_session, "a")
    await _create_item(repo, db_session, "b")
    assert await repo.count_by_user(user_id=1) == 2


async def test_count_by_user_isolation(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await _create_item(repo, db_session, "user1 item", user_id=1)
    await _create_item(repo, db_session, "user2 item", user_id=2)
    assert await repo.count_by_user(user_id=1) == 1


async def test_search_finds_content_match(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await _create_item(repo, db_session, "coffee shop receipt")
    await _create_item(repo, db_session, "grocery list")

    results = await repo.search(user_id=1, query="coffee")
    assert len(results) == 1
    assert results[0].content == "coffee shop receipt"


async def test_search_finds_description_match(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await _create_item(repo, db_session, "photo.jpg", description="beach sunset photo")
    await _create_item(repo, db_session, "doc.pdf", description="tax document")

    results = await repo.search(user_id=1, query="beach")
    assert len(results) == 1
    assert results[0].content == "photo.jpg"


async def test_search_case_insensitive(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await _create_item(repo, db_session, "Buy Milk at Store")

    results = await repo.search(user_id=1, query="buy milk")
    assert len(results) == 1


async def test_search_no_results_returns_empty(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await _create_item(repo, db_session, "something else")

    results = await repo.search(user_id=1, query="unicorn")
    assert results == []


async def test_search_user_isolation(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await _create_item(repo, db_session, "secret note", user_id=1)
    await _create_item(repo, db_session, "another secret", user_id=2)

    results = await repo.search(user_id=1, query="secret")
    assert len(results) == 1
    assert results[0].user_id == 1
