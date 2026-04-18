from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository


async def test_create_returns_item(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=1, type=ItemType.link, content="https://example.com")
    await db_session.commit()
    assert isinstance(item, Item)
    assert item.id is not None
    assert item.user_id == 1
    assert item.type == ItemType.link
    assert item.content == "https://example.com"


async def test_get_by_user_returns_items(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    for i in range(3):
        await repo.create(user_id=42, type=ItemType.note, content=f"note {i}")
    await db_session.commit()

    items = await repo.get_by_user(42)
    assert len(items) == 3
    assert all(it.user_id == 42 for it in items)


async def test_get_by_user_respects_limit(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    for i in range(15):
        await repo.create(user_id=99, type=ItemType.note, content=f"note {i}")
    await db_session.commit()

    items = await repo.get_by_user(99, limit=5)
    assert len(items) == 5


async def test_get_by_user_returns_only_own_items(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await repo.create(user_id=1, type=ItemType.note, content="mine")
    await repo.create(user_id=2, type=ItemType.note, content="not mine")
    await db_session.commit()

    items = await repo.get_by_user(1)
    assert all(it.user_id == 1 for it in items)
    assert len(items) == 1


async def test_get_missing_embedding_returns_only_unindexed(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    a = await repo.create(user_id=1, type=ItemType.note, content="a")
    b = await repo.create(user_id=1, type=ItemType.note, content="b")
    await db_session.commit()

    # Index only one of them.
    await repo.update_embedding(a.id, [0.1] * 1024)
    await db_session.commit()

    missing = await repo.get_missing_embedding(limit=10)
    missing_ids = {item.id for item in missing}
    assert b.id in missing_ids
    assert a.id not in missing_ids


async def test_get_missing_embedding_respects_limit(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    for i in range(5):
        await repo.create(user_id=1, type=ItemType.note, content=f"n{i}")
    await db_session.commit()

    missing = await repo.get_missing_embedding(limit=2)
    assert len(missing) == 2


async def test_update_embedding_noop_for_missing_item(db_session: AsyncSession) -> None:
    """Silently skip when the Item no longer exists (e.g. deleted by the user mid-reindex)."""
    import uuid

    repo = ItemRepository(db_session)
    # Using a random UUID that doesn't match any row — must not raise.
    await repo.update_embedding(uuid.uuid4(), [0.0] * 1024)


async def test_update_scraped_text_persists_value(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=1, type=ItemType.link, content="https://example.com")
    await db_session.commit()

    await repo.update_scraped_text(item.id, "full page body here")
    await db_session.commit()

    stored = await repo.get_by_id(item.id)
    assert stored is not None
    assert stored.scraped_text == "full page body here"


async def test_update_scraped_text_noop_for_missing_item(db_session: AsyncSession) -> None:
    """Silently skip when the Item no longer exists (e.g. deleted between save and summarize)."""
    import uuid

    repo = ItemRepository(db_session)
    # Using a random UUID that doesn't match any row — must not raise.
    await repo.update_scraped_text(uuid.uuid4(), "page body")


async def test_get_by_id_returns_item(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=1, type=ItemType.link, content="https://x.com")
    await db_session.commit()

    result = await repo.get_by_id(item.id)
    assert result is not None
    assert result.id == item.id


async def test_get_by_id_returns_none_for_unknown_id(db_session: AsyncSession) -> None:
    import uuid

    repo = ItemRepository(db_session)
    assert await repo.get_by_id(uuid.uuid4()) is None
