"""Unit tests for IdeaRepository.search_by_embedding.

pgvector's cosine-distance operator is PostgreSQL-only, so we mock the session
and inspect the emitted query instead of running it against SQLite.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.idea import Idea
from bot.models.item import Item, ItemType
from bot.repositories.idea_repository import IdeaRepository


def _render(stmt: object) -> tuple[str, dict[str, object]]:
    """Compile ``stmt`` against the PostgreSQL dialect; return (sql, bind params)."""
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


def _make_mock_result(rows: list[tuple[Item, Idea, float]]) -> MagicMock:
    """Wrap ``rows`` into an object that mimics ``session.execute(...).all()``."""
    mock = MagicMock()
    mock.all.return_value = rows
    return mock


def _make_item(content: str = "x") -> Item:
    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.content = content
    return item


def _make_idea(tags: list[str] | None = None) -> Idea:
    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = tags or []
    return idea


async def test_search_by_embedding_returns_triples_with_score_one_minus_distance() -> None:
    parent_a = _make_item("a")
    parent_b = _make_item("b")
    idea_a = _make_idea(["t1"])
    idea_b = _make_idea(["t2"])
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        return_value=_make_mock_result([(parent_a, idea_a, 0.2), (parent_b, idea_b, 0.5)])
    )
    repo = IdeaRepository(session)

    results = await repo.search_by_embedding([0.1, 0.2, 0.3, 0.4], user_id=1, limit=5)

    assert results == [(parent_a, idea_a, 0.8), (parent_b, idea_b, 0.5)]
    session.execute.assert_awaited_once()


async def test_search_by_embedding_query_filters_user_id_type_idea_and_not_null() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=_make_mock_result([]))
    repo = IdeaRepository(session)

    await repo.search_by_embedding([0.1] * 4, user_id=77, limit=4)

    stmt = session.execute.await_args.args[0]
    sql, params = _render(stmt)
    # Cosine-distance operator must be present.
    assert "<=>" in sql
    # Must join items → ideas.
    assert "JOIN ideas" in sql
    # User isolation must be applied.
    assert "items.user_id" in sql
    # Must filter on items.type so rows belong to ideas only.
    assert "items.type" in sql
    # embedding IS NOT NULL guard on the Idea side.
    assert "ideas.embedding IS NOT NULL" in sql
    # LIMIT, user_id, and the idea type must reach the parameter set.
    assert 4 in params.values()
    assert 77 in params.values()
    assert ItemType.idea in params.values()


async def test_search_by_embedding_empty_when_no_rows() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=_make_mock_result([]))
    repo = IdeaRepository(session)

    assert await repo.search_by_embedding([0.1] * 4, user_id=1, limit=10) == []


async def test_search_by_embedding_orders_by_distance_ascending() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=_make_mock_result([]))
    repo = IdeaRepository(session)

    await repo.search_by_embedding([0.1] * 4, user_id=1, limit=3)

    stmt = session.execute.await_args.args[0]
    sql, _ = _render(stmt)
    assert "ORDER BY" in sql
    assert "<=>" in sql  # distance expression drives the ORDER BY
    assert " ASC" in sql
