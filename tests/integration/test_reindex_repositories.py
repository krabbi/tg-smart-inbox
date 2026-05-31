"""Integration tests for the unindexed-records repository methods used by ReindexService.

These verify the SQL filters and ordering used by ``list_without_embedding``,
``count_without_embedding`` and ``IdeaRepository.get_by_id_for_user`` against a
real (in-memory SQLite) database. User isolation is part of the contract — a row
that belongs to another ``user_id`` must never appear in the result set.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.idea import Idea
from bot.models.item import Item, ItemType
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository

USER_A = 1001
USER_B = 2002


async def _backdate_item(session: AsyncSession, item_id: uuid.UUID, delta_seconds: int) -> None:
    """Force ``Item.created_at`` to a known offset so ORDER BY is deterministic."""
    await session.execute(
        update(Item)
        .where(Item.id == item_id)
        .values(created_at=datetime.now(tz=UTC) - timedelta(seconds=delta_seconds))
    )


# --- ItemRepository.list_without_embedding ----------------------------------


async def test_item_list_without_embedding_filters_null_only(
    db_session: AsyncSession,
) -> None:
    repo = ItemRepository(db_session)
    indexed = await repo.create(user_id=USER_A, type=ItemType.note, content="indexed")
    unindexed = await repo.create(user_id=USER_A, type=ItemType.note, content="unindexed")
    await db_session.commit()
    await repo.update_embedding(indexed.id, [0.1] * 1024)
    await db_session.commit()

    rows = await repo.list_without_embedding(USER_A, limit=10)

    ids = [it.id for it in rows]
    assert ids == [unindexed.id]


async def test_item_list_without_embedding_orders_oldest_first(
    db_session: AsyncSession,
) -> None:
    repo = ItemRepository(db_session)
    older = await repo.create(user_id=USER_A, type=ItemType.note, content="older")
    await repo.create(user_id=USER_A, type=ItemType.note, content="newer")
    await db_session.commit()
    await _backdate_item(db_session, older.id, delta_seconds=60)
    await db_session.commit()

    rows = await repo.list_without_embedding(USER_A, limit=10)

    assert [it.content for it in rows] == ["older", "newer"]


async def test_item_list_without_embedding_respects_limit(
    db_session: AsyncSession,
) -> None:
    repo = ItemRepository(db_session)
    for i in range(5):
        await repo.create(user_id=USER_A, type=ItemType.note, content=f"n{i}")
    await db_session.commit()

    rows = await repo.list_without_embedding(USER_A, limit=2)

    assert len(rows) == 2


async def test_item_list_without_embedding_excludes_other_users(
    db_session: AsyncSession,
) -> None:
    repo = ItemRepository(db_session)
    own = await repo.create(user_id=USER_A, type=ItemType.note, content="own")
    await repo.create(user_id=USER_B, type=ItemType.note, content="foreign")
    await db_session.commit()

    rows = await repo.list_without_embedding(USER_A, limit=10)

    assert [it.id for it in rows] == [own.id]


async def test_item_count_without_embedding_isolates_per_user(
    db_session: AsyncSession,
) -> None:
    repo = ItemRepository(db_session)
    a = await repo.create(user_id=USER_A, type=ItemType.note, content="a1")
    await repo.create(user_id=USER_A, type=ItemType.note, content="a2")
    await repo.create(user_id=USER_B, type=ItemType.note, content="b1")
    await db_session.commit()
    # Index one of A's items so the count drops to 1.
    await repo.update_embedding(a.id, [0.1] * 1024)
    await db_session.commit()

    assert await repo.count_without_embedding(USER_A) == 1
    assert await repo.count_without_embedding(USER_B) == 1


# --- IdeaRepository.list_without_embedding ----------------------------------


async def test_idea_list_without_embedding_filters_null_only(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    item_indexed = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="indexed")
    indexed_idea = await idea_repo.save(item_id=item_indexed.id, tags=["a"])
    item_unindexed = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="unindexed")
    await idea_repo.save(item_id=item_unindexed.id, tags=["b"])
    await db_session.commit()

    await idea_repo.update_embedding(indexed_idea.id, [0.1] * 1024)
    await db_session.commit()

    rows = await idea_repo.list_without_embedding(USER_A, limit=10)

    assert len(rows) == 1
    parent, idea = rows[0]
    assert parent.id == item_unindexed.id
    assert idea.embedding is None


async def test_idea_list_without_embedding_orders_oldest_first(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    older_item = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="older")
    await idea_repo.save(item_id=older_item.id, tags=[])
    newer_item = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="newer")
    await idea_repo.save(item_id=newer_item.id, tags=[])
    await db_session.commit()
    await _backdate_item(db_session, older_item.id, delta_seconds=60)
    await db_session.commit()

    rows = await idea_repo.list_without_embedding(USER_A, limit=10)
    contents = [item.content for item, _ in rows]

    assert contents == ["older", "newer"]


async def test_idea_list_without_embedding_respects_limit(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    for i in range(5):
        item = await item_repo.create(user_id=USER_A, type=ItemType.idea, content=f"i{i}")
        await idea_repo.save(item_id=item.id, tags=[])
    await db_session.commit()

    rows = await idea_repo.list_without_embedding(USER_A, limit=3)

    assert len(rows) == 3


async def test_idea_list_without_embedding_excludes_other_users(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    own_item = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="own")
    await idea_repo.save(item_id=own_item.id, tags=[])
    foreign_item = await item_repo.create(user_id=USER_B, type=ItemType.idea, content="foreign")
    await idea_repo.save(item_id=foreign_item.id, tags=[])
    await db_session.commit()

    rows = await idea_repo.list_without_embedding(USER_A, limit=10)

    assert len(rows) == 1
    assert rows[0][0].id == own_item.id


async def test_idea_count_without_embedding_isolates_per_user(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    for _ in range(2):
        it = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="a")
        await idea_repo.save(item_id=it.id, tags=[])
    foreign = await item_repo.create(user_id=USER_B, type=ItemType.idea, content="b")
    await idea_repo.save(item_id=foreign.id, tags=[])
    await db_session.commit()

    assert await idea_repo.count_without_embedding(USER_A) == 2
    assert await idea_repo.count_without_embedding(USER_B) == 1


# --- IdeaRepository.get_by_id_for_user --------------------------------------


async def test_idea_get_by_id_for_user_returns_idea_for_owner(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    parent = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="hi")
    idea = await idea_repo.save(item_id=parent.id, tags=["x"])
    await db_session.commit()

    result = await idea_repo.get_by_id_for_user(idea.id, USER_A)

    assert result is not None
    assert result.id == idea.id


async def test_idea_get_by_id_for_user_returns_none_for_foreign_owner(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    parent = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="hi")
    idea = await idea_repo.save(item_id=parent.id, tags=[])
    await db_session.commit()

    assert await idea_repo.get_by_id_for_user(idea.id, USER_B) is None


async def test_idea_get_by_id_for_user_returns_none_for_unknown_id(
    db_session: AsyncSession,
) -> None:
    idea_repo = IdeaRepository(db_session)
    assert await idea_repo.get_by_id_for_user(uuid.uuid4(), USER_A) is None


# --- A model-level Idea instance to exercise the relationship --------------


async def test_idea_get_by_id_for_user_returned_object_is_an_idea(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    parent = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="check")
    idea = await idea_repo.save(item_id=parent.id, tags=["tag"])
    await db_session.commit()

    fetched = await idea_repo.get_by_id_for_user(idea.id, USER_A)
    assert isinstance(fetched, Idea)
    assert fetched.tags == ["tag"]
