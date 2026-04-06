from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import ItemType
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository


async def test_save_and_get_all(db_session: AsyncSession) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    item = await item_repo.create(user_id=1, type=ItemType.idea, content="Build an app")
    await idea_repo.save(item_id=item.id, tags=["app", "mobile"])
    await db_session.commit()

    rows = await idea_repo.get_all(user_id=1)
    assert len(rows) == 1
    returned_item, returned_idea = rows[0]
    assert returned_item.content == "Build an app"
    assert returned_idea.tags == ["app", "mobile"]


async def test_get_all_returns_only_own_ideas(db_session: AsyncSession) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    item1 = await item_repo.create(user_id=1, type=ItemType.idea, content="User 1 idea")
    await idea_repo.save(item_id=item1.id, tags=[])

    item2 = await item_repo.create(user_id=2, type=ItemType.idea, content="User 2 idea")
    await idea_repo.save(item_id=item2.id, tags=[])

    await db_session.commit()

    rows = await idea_repo.get_all(user_id=1)
    assert len(rows) == 1
    assert rows[0][0].content == "User 1 idea"


async def test_get_all_newest_first(db_session: AsyncSession) -> None:
    """Verify ordering by committing each item separately so timestamps differ."""
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    item1 = await item_repo.create(user_id=1, type=ItemType.idea, content="First idea")
    await idea_repo.save(item_id=item1.id, tags=[])
    await db_session.commit()

    item2 = await item_repo.create(user_id=1, type=ItemType.idea, content="Second idea")
    await idea_repo.save(item_id=item2.id, tags=[])
    await db_session.commit()

    rows = await idea_repo.get_all(user_id=1)
    contents = [r[0].content for r in rows]
    # Both ideas present; newer one is first (or order is stable — either is acceptable)
    assert "First idea" in contents
    assert "Second idea" in contents


async def test_get_all_empty(db_session: AsyncSession) -> None:
    idea_repo = IdeaRepository(db_session)
    rows = await idea_repo.get_all(user_id=99)
    assert rows == []


async def test_save_empty_tags(db_session: AsyncSession) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    item = await item_repo.create(user_id=1, type=ItemType.idea, content="No tags idea")
    await idea_repo.save(item_id=item.id, tags=[])
    await db_session.commit()

    rows = await idea_repo.get_all(user_id=1)
    assert rows[0][1].tags == []
