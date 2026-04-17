"""Unit tests for ItemRepository.search_by_embedding.

pgvector's cosine-distance operator is PostgreSQL-only, so we mock the session
and inspect the emitted query instead of running it against SQLite.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item
from bot.repositories.item_repository import ItemRepository


def _render(stmt: object) -> tuple[str, dict[str, object]]:
    """Compile ``stmt`` against the PostgreSQL dialect; return (sql, bind params).

    The vector literal cannot be rendered as a SQL literal, so bind params are
    inspected separately instead of using ``literal_binds``.
    """
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


def _make_mock_result(rows: list[tuple[Item, float]]) -> MagicMock:
    """Wrap ``rows`` into an object that mimics ``session.execute(...).all()``."""
    mock = MagicMock()
    mock.all.return_value = rows
    return mock


def _make_item(content: str = "x") -> Item:
    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.content = content
    return item


async def test_search_by_embedding_returns_items_with_score_one_minus_distance() -> None:
    item_a = _make_item("a")
    item_b = _make_item("b")
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=_make_mock_result([(item_a, 0.1), (item_b, 0.4)]))
    repo = ItemRepository(session)

    results = await repo.search_by_embedding([0.1, 0.2, 0.3, 0.4], user_id=1, limit=5)

    assert results == [(item_a, 0.9), (item_b, 0.6)]
    session.execute.assert_awaited_once()


async def test_search_by_embedding_query_uses_cosine_distance_user_filter_and_null_guard() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=_make_mock_result([]))
    repo = ItemRepository(session)

    await repo.search_by_embedding([0.1] * 4, user_id=99, limit=7)

    stmt = session.execute.await_args.args[0]
    sql, params = _render(stmt)
    # Cosine-distance operator must be present.
    assert "<=>" in sql
    # User isolation must be applied at the SQL level.
    assert "items.user_id" in sql
    # embedding IS NOT NULL guard must filter out unindexed rows.
    assert "items.embedding IS NOT NULL" in sql
    # LIMIT and user_id must reach the parameter set with the caller's values.
    assert 7 in params.values()
    assert 99 in params.values()


async def test_search_by_embedding_returns_empty_when_no_rows() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=_make_mock_result([]))
    repo = ItemRepository(session)

    assert await repo.search_by_embedding([0.0] * 4, user_id=1, limit=10) == []


async def test_search_by_embedding_orders_by_distance_ascending() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=_make_mock_result([]))
    repo = ItemRepository(session)

    await repo.search_by_embedding([0.1] * 4, user_id=1, limit=3)

    stmt = session.execute.await_args.args[0]
    sql, _ = _render(stmt)
    assert "ORDER BY" in sql
    assert "<=>" in sql  # distance expression drives the ORDER BY
    assert " ASC" in sql
